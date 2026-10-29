# -*- coding: utf-8 -*-
"""
fitness v1 本地版 —— 拍照记餐 + 剩余额度（零依赖，仅 Python 标准库）
=====================================================================
链路：手机页面 → 本服务 → 视觉模型识别 → 热量降级链(查表→模型估) → SQLite → 剩余额度
多用户：beifeng / gagayouna，user_id 仅用于选对热量档案（A 简化版，无数据隔离）
配置：code/config.json（首次启动自动从 config.example.json 生成）

接口：
  GET  /                 手机页面
  GET  /api/health       健康检查
  GET  /api/today?user=  今日记录+汇总+剩余
  POST /api/meal         multipart: photo(可选) / text(可选) / user(必填)
  POST /api/correct      JSON: {id, action:"delete"|"edit", kcal?, food?}
"""
import base64
import gzip
import hashlib
import hmac
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

try:  # Windows 控制台中文
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATA = os.path.join(BASE, "data")
DB_PATH = os.path.join(DATA, "fitness.db")
PROFILES_DIR = os.path.join(DATA, "profiles")
FOOD_TABLE_MD = os.path.join(DATA, "常吃食物热量表.md")
CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
CFG_EXAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.example.json")

USERS = {"beifeng": "邶风", "gagayouna": "gagayouna"}

ANALYZE_PROMPT = (
    "你是减肥管家的食物识别与意图判断模块。根据用户输入（文字或图片）和【今日已有记录】判断意图。\n"
    '只输出 JSON：{"action":"record"或"correct","id":整数或0,"items":[{"food":"食物名","portion":"份量描述",'
    '"meal_type":"早餐|午餐|晚餐|加餐","kcal":整数中值,"kcal_low":整数,"kcal_high":整数,'
    '"protein_g":整数,"fat_g":整数,"carb_g":整数}]}\n'
    "意图判断规则："
    "① 描述新吃的食物 → action=record。"
    "② 更正最近一条记录 → action=correct，id=被更正记录的 id，items 填新描述。"
    "更正的信号：用了「不对/其实是/说错了」等措辞，或对上一条**同类食物**给出新名称"
    "（例：上条记录「咖啡」，用户说「燕麦拿铁」→ 这是把咖啡更正为燕麦拿铁）。"
    "③ 明显是另一餐或全新食物 → record；判断不了 → record。\n"
    "meal_type：按用户时间词判断（早上→早餐等），没提则省略。"
    "份量：没说明数量禁止臆造，写「未说明数量」，按常见单份估。"
    "④ 若用户明确说明照片是某一餐吃剩的部分、要求扣回 → 输出负数热量项用于抵扣"
    "（food 加前缀「扣回:」，kcal/kcal_low/kcal_high/protein_g/fat_g/carb_g 均为负值，portion 写剩余比例）。"
    "热量区间 ±20%。识别不到食物 → {\"action\":\"record\",\"id\":0,\"items\":[]}。"
    "⑤ 输入可能是语音转写的对话碎片（含寒暄/疑问/过程描述）：只提取**确定吃了**的食物，"
    "忽略闲聊和无法确定是否入口的内容；【今日已有记录】里已存在的同餐次同食物不要重复输出。"
    "⑥ 「晚上还有八只虾」「热一下」「煮熟了」「不热了直接吃」这类描述 = 现在就吃这些剩菜，"
    "正常提取为当前餐次的记录，不要因为是对话形式而跳过。"
    "⑦ 用户描述训练/运动（如练了胸、骑车40分钟、深蹲4组12个）→ action=training，"
    "items 填 {\"action\":\"动作名\",\"sets_reps\":\"组次\",\"duration_min\":分钟,"
    "\"kcal\":预计消耗中值,\"kcal_low\":低,\"kcal_high\":高}（按动作类型和时长估消耗，力量训练约20分钟150~250千卡）。"
)

# ---------------------------------------------------------------- 配置

def load_config():
    if not os.path.exists(CFG_PATH):
        with open(CFG_EXAMPLE, "r", encoding="utf-8") as f:
            cfg = f.read()
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            f.write(cfg)
        print("已从 config.example.json 生成 config.json，请填入 api_key")
    with open(CFG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


CFG = load_config()

PLAN_PARSE_PROMPT = (
    "把用户的每周训练计划文本解析成结构化 JSON。只输出 JSON，不要其他文字："
    '{"days":[{"dow":"周一","parts":[{"name":"动作/部位名","sets_reps":"组次组数如4x12"}]}]}'
    "规则：dow 只能取 周一~周日；按原文顺序完整解析，不遗漏不臆造；"
    "原文没提的动作不要编。无法解析 → {\"days\":[]}。"
)

# 复用已验证的热量计算（Mifflin-St Jeor）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
from fitness_lib import plan as calc_plan  # noqa: E402


class ApiError(Exception):
    """业务校验错误 → 400"""


def num_field(j, key, lo, hi, int_=False):
    """校验并取数值字段；未填返回 None"""
    v = j.get(key)
    if v in (None, ""):
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise ApiError(f"{key} 不是数字")
    if not lo <= v <= hi:
        raise ApiError(f"{key} 超出合理范围 {lo}~{hi}")
    return int(v) if int_ else v

# ---------------------------------------------------------------- 数据库

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    # 部署(FaaS)环境可能没有 data 目录——建库前先确保目录存在（部署适配，勿删）
    os.makedirs(DATA, exist_ok=True)
    os.makedirs(PROFILES_DIR, exist_ok=True)
    os.makedirs(os.path.join(DATA, "meals"), exist_ok=True)
    os.makedirs(os.path.join(DATA, "plans"), exist_ok=True)
    with db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")  # 并发读写（上传+汇总）不再偶发 database locked
        conn.execute(
            """CREATE TABLE IF NOT EXISTS meals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                date TEXT NOT NULL,
                meal_type TEXT NOT NULL,
                food TEXT NOT NULL,
                kcal INTEGER, kcal_low INTEGER, kcal_high INTEGER,
                protein_g INTEGER,
                note TEXT DEFAULT '',
                created_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS workouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                date TEXT NOT NULL,
                action TEXT NOT NULL,
                sets_reps TEXT DEFAULT '',
                duration_min INTEGER,
                est_kcal INTEGER,
                note TEXT DEFAULT '',
                created_at TEXT
            )"""
        )
        for col in ("fat_g INTEGER", "carb_g INTEGER", "portion TEXT"):  # 老库迁移：宏量+份量
            try:
                conn.execute("ALTER TABLE meals ADD COLUMN " + col)
            except sqlite3.OperationalError:
                pass

# ---------------------------------------------------------------- 档案 & 热量表

def profile_targets(user_id):
    path = os.path.join(PROFILES_DIR, user_id + ".json")
    with open(path, "r", encoding="utf-8") as f:
        p = json.load(f)
    t = p["targets"]
    return {"kcal": int(t["daily_kcal"]), "protein": int(t["protein_g"]),
            "fat": int(t.get("fat_g") or 0), "carb": int(t.get("carb_g") or 0),
            "name": p["display_name"]}


def load_food_table():
    """解析 data/常吃食物热量表.md 的 markdown 表格 → {食物名: (kcal, protein)}"""
    out = {}
    try:
        with open(FOOD_TABLE_MD, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) < 4 or cells[0] in ("食物", "") or set(cells[0]) <= {"-", " ", ":"}:
                    continue
                try:
                    kcal = int(re.sub(r"[^0-9]", "", cells[2]) or 0)
                    protein = int(re.sub(r"[^0-9]", "", cells[3]) or 0)
                except ValueError:
                    continue
                if cells[0] and kcal:
                    out[cells[0]] = (kcal, protein)
    except FileNotFoundError:
        pass
    return out


DOW = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

def plan_path(user_id):
    return os.path.join(DATA, "plans", "weekly_plan_%s.json" % user_id)

def load_plan(user_id):
    p = plan_path(user_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def save_plan(user_id, plan):
    os.makedirs(os.path.join(DATA, "plans"), exist_ok=True)
    with open(plan_path(user_id), "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

def plan_hint(user_id, date_str):
    """返回今天计划提示（无计划/今天无安排 → None）"""
    plan = load_plan(user_id)
    if not plan:
        return None
    try:
        dow = DOW[datetime.strptime(date_str, "%Y-%m-%d").weekday()]
    except ValueError:
        return None
    for d in plan.get("days", []):
        if d.get("dow") == dow:
            parts = "、".join((p.get("name") or "") + " " + (p.get("sets_reps") or "")
                              for p in d.get("parts", []))
            if parts.strip():
                return "📋 今天计划：" + parts.strip()
    return None

def week_workouts(user_id):
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    wk_start = monday.strftime("%Y-%m-%d")
    with db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT id,date,action,sets_reps,est_kcal FROM workouts WHERE user_id=? AND date>=? ORDER BY id",
            (user_id, wk_start)).fetchall()]

def table_lookup(food):
    """查表：精确命中，或近似命中（food 与表名长度差 ≤2，如"半碗米饭"↔"米饭"）。
    组合餐名（"一碗米饭一份蔬菜"）长度差过大 → 不命中，走 [估]。"""
    table = load_food_table()
    if food in table:
        return table[food]
    for name, v in table.items():
        if len(name) >= 2 and (name in food or food in name) and abs(len(food) - len(name)) <= 2:
            return v
    return None


def infer_meal_type():
    h = datetime.now().hour
    if h < 10:
        return "早餐"
    if h < 14:
        return "午餐"
    if h < 17:
        return "加餐"
    if h < 21:
        return "晚餐"
    return "加餐"

# ---------------------------------------------------------------- 模型调用

def llm_analyze(text, image_b64, recent=None, extra="", llm_cfg=None, timeout=120, prompt=None):
    """识别食物+判断意图；mock 模式返回固定结果。协议按配置：openai(默认) / anthropic
    llm_cfg：可选的独立模型配置（文字通道快模型），缺省用主配置
    prompt：覆盖默认的 ANALYZE_PROMPT（计划解析等场景用）"""
    if CFG.get("mock"):
        src = text or "(图片)"
        return {"action": "record", "id": 0,
                "items": [{"food": src[:20] or "示例餐", "portion": "1份",
                           "kcal": 400, "kcal_low": 320, "kcal_high": 480,
                           "protein_g": 15, "fat_g": 12, "carb_g": 45}]}
    llm = llm_cfg or CFG["llm"]
    ctx = ""
    if recent:
        ctx += "\n【今日已有记录】" + json.dumps(recent, ensure_ascii=False)
    if text:
        ctx += "\n用户输入：" + text
    ctx += extra
    if llm.get("protocol") == "anthropic":
        return _anthropic_analyze(text, image_b64, llm, ctx, timeout=timeout, prompt=prompt)
    content = []
    if image_b64:
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + image_b64}})
    content.append({"type": "text", "text": (prompt or ANALYZE_PROMPT) + ctx})
    payload = json.dumps({"model": llm["model"], "messages": [{"role": "user", "content": content}],
                          "temperature": 0.2}).encode("utf-8")
    req = urllib.request.Request(
        llm["base_url"].rstrip("/") + "/chat/completions", data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + llm["api_key"]})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    raw = data["choices"][0]["message"]["content"]
    return _extract_json(raw)


def _anthropic_analyze(text, image_b64, llm, extra="", timeout=120, prompt=None):
    """Anthropic /v1/messages 协议（如火山方舟 coding 网关）。
    用流式请求：思考型模型思考阶段持续吐 delta，连接不会因长时间无响应被网关掐掉
    （非流式在网关高峰会被掐 → 用户端 TimeoutError）。
    思考占满 max_tokens 导致正文为空 → 重试一次。"""
    content = []
    if image_b64:
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}})
    content.append({"type": "text", "text": (prompt or ANALYZE_PROMPT) + extra})
    last_err = ""
    for _ in range(2):
        payload = json.dumps({"model": llm["model"], "max_tokens": 6000, "stream": True,
                              "messages": [{"role": "user", "content": content}]}).encode("utf-8")
        req = urllib.request.Request(
            llm["base_url"].rstrip("/") + "/v1/messages", data=payload,
            headers={"Content-Type": "application/json", "x-api-key": llm["api_key"],
                     "anthropic-version": "2023-06-01", "accept": "text/event-stream"})
        raw = ""
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for rawline in resp:
                    line = rawline.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        ev = json.loads(data)
                    except ValueError:
                        continue
                    if ev.get("type") == "content_block_delta":
                        d = ev.get("delta", {})
                        if d.get("type") == "text_delta":
                            raw += d.get("text", "")
        except urllib.error.HTTPError:
            raise  # 4xx/5xx 交给上层
        except Exception as ex:
            last_err = repr(ex)
            continue  # 网络中断/超时 → 重试一次
        if raw.strip():
            return _extract_json(raw)
        last_err = "模型只输出思考未给正文"
    raise ValueError(f"两次尝试均未得到正文（{last_err}），请稍后重试")


def _extract_json(raw):
    m = re.search(r"\{.*\}", raw, re.S)  # 抠出第一段 JSON（贪婪到最后一个 }）
    if not m:
        raise ValueError("模型未返回 JSON：" + raw[:200])
    return json.loads(m.group(0))


def resolve_item(item, user_id):
    """热量来源降级链：查表命中 → 覆盖为表值 [表]；否则模型值 [估]"""
    hit = table_lookup(item.get("food", ""))
    if hit:
        item["kcal"], item["protein_g"] = hit
        item["note"] = "[表]"
        item["kcal_low"] = int(item["kcal"] * 0.9)
        item["kcal_high"] = int(item["kcal"] * 1.1)
    else:
        item["note"] = "[估]"
    return item

# ---------------------------------------------------------------- 业务

def valid_date(ds):
    """前端传入的记录日期：格式合法且不晚于今天才收，否则回落今天（防未来日期/脏数据）"""
    today = datetime.now().strftime("%Y-%m-%d")
    if ds and re.match(r"^\d{4}-\d{2}-\d{2}$", ds) and ds <= today:
        return ds
    return today


def insert_meals(user_id, items, date=None):
    date = valid_date(date)
    meal_type = infer_meal_type()
    ids = []
    with db() as conn:
        for it in items:
            cur = conn.execute(
                "INSERT INTO meals (user_id,date,meal_type,food,kcal,kcal_low,kcal_high,protein_g,note,created_at,fat_g,carb_g,portion)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, date, it.get("meal_type") or meal_type, it.get("food", "未知"),
                 it.get("kcal"), it.get("kcal_low"), it.get("kcal_high"),
                 it.get("protein_g"), it.get("note", ""), datetime.now().isoformat(timespec="seconds"),
                 it.get("fat_g"), it.get("carb_g"), it.get("portion", "")))
            ids.append(cur.lastrowid)
    return ids


def today_summary(user_id, date_str=None):
    date = date_str if (date_str and re.match(r"^\d{4}-\d{2}-\d{2}$", date_str)) else datetime.now().strftime("%Y-%m-%d")
    tgt = profile_targets(user_id)
    with db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id,meal_type,food,kcal,kcal_low,kcal_high,protein_g,note,fat_g,carb_g,portion FROM meals"
            " WHERE user_id=? AND date=? ORDER BY id", (user_id, date))]
        for r in rows:
            r["photo"] = 1 if os.path.exists(os.path.join(DATA, "meals", "record_%d.jpg" % r["id"])) else 0
    eaten = sum(r["kcal"] or 0 for r in rows)
    protein = sum(r["protein_g"] or 0 for r in rows)
    fat = sum(r["fat_g"] or 0 for r in rows)
    carb = sum(r["carb_g"] or 0 for r in rows)
    remaining = tgt["kcal"] - eaten
    return {"user": user_id, "name": tgt["name"], "date": date, "records": rows,
            "eaten": eaten, "protein": protein, "fat": fat, "carb": carb,
            "target": tgt["kcal"], "protein_target": tgt["protein"],
            "remaining": remaining,
            "dinner_tip": (dinner_tip(rows, remaining) if date == datetime.now().strftime("%Y-%m-%d") else None)}


def dinner_tip(rows, remaining):
    """午餐后给出晚餐预算与克数建议；预算=剩余×90%，单餐上限 800kcal"""
    has_lunch = any(r["meal_type"] == "午餐" for r in rows)
    if not has_lunch and datetime.now().hour < 13:
        return None
    if remaining <= 0:
        return "晚餐预算已用完，建议高蛋白低热量（水煮蛋+蔬菜）"
    raw = int(remaining * 0.9)
    budget = min(raw, 800)
    rest = budget - 90  # 蔬菜 300g 固定约 90kcal
    rice = max(int((rest * 0.55) / 1.16 / 10) * 10, 0)   # 米饭 ~116kcal/100g
    meat = max(int((rest * 0.45) / 1.43 / 10) * 10, 0)   # 瘦肉 ~143kcal/100g
    tip = f"晚餐建议 ≈{budget}kcal ≈ 米饭{rice}g + 瘦肉{meat}g + 蔬菜300g"
    if raw > 800 and remaining - 800 > 200:
        tip += "｜今天余量较大"
    return tip


def build_card(items, summary, verb="记录"):
    low = sum(i.get("kcal_low") or 0 for i in items)
    high = sum(i.get("kcal_high") or 0 for i in items)
    protein = sum(i.get("protein_g") or 0 for i in items)
    names = "、".join(i.get("food", "?") + (i.get("portion", "")) for i in items)
    mid = sum(i.get("kcal") or 0 for i in items)
    meal_type = items[0].get("meal_type") or infer_meal_type()
    day = "今日" if summary["date"] == datetime.now().strftime("%Y-%m-%d") else summary["date"][5:] + " 当天"
    return (f"✅ 已{verb}{meal_type}：{names}，约{mid}kcal（区间{low}~{high}）｜蛋白{protein}g\n"
            f"📊 {summary['name']}{day}已吃 {summary['eaten']}/{summary['target']} kcal｜"
            f"蛋白 {summary['protein']}/{summary['protein_target']}g\n"
            f"🔜 剩余 {summary['remaining']} kcal")

# ---------------------------------------------------------------- 页面（静态文件，见 code/web/）
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
def _load_web(name):
    with open(os.path.join(WEB_DIR, name), "rb") as f:
        return f.read()

PAGES = {n: _load_web(n) for n in ("index.html", "app.css", "app.js", "manifest.json")}

_icon_cache = {}
def _icon(size):
    """零依赖PNG应用图标：薄荷底+白色75%进度环（呼应环形热量进度）。懒生成防拖慢启动"""
    if size in _icon_cache:
        return _icon_cache[size]
    import math, struct, zlib
    bg = (87, 195, 116)                       # --color-primary
    fg = (255, 255, 255, 255)
    tr = (206, 239, 215, 255)                 # 环轨道：实色浅薄荷（避免启动器alpha合成差异）
    cx = cy = size / 2.0
    R, half = size * 0.32, size * 0.0425
    raw = bytearray()
    for y in range(size):
        raw.append(0)                          # PNG行滤波字节
        for x in range(size):
            d = math.hypot(x + .5 - cx, y + .5 - cy)
            if abs(d - R) <= half:
                ang = (math.degrees(math.atan2(x + .5 - cx, -(y + .5 - cy))) + 360.0) % 360.0
                raw += bytes(fg if ang <= 270 else tr)
            else:
                raw += bytes(bg + (255,))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))
    _icon_cache[size] = png
    return png
ETAGS = {n: '"' + hashlib.md5(d).hexdigest()[:16] + '"' for n, d in PAGES.items()}

# ---------------------------------------------------------------- HTTP

class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _authed(self):
        code = CFG.get("access_code") or ""
        if not code:
            return True
        return hmac.compare_digest(self.headers.get("X-Access-Token") or "", code)

    def _serve_static(self, name, ctype):
        """页面静态文件：ETag 协商缓存 + gzip。重复打开页面命中304零下载，
        首次打开 60KB→~15KB（公网4G体感显著）"""
        data = PAGES[name]
        et = ETAGS[name]
        if self.headers.get("If-None-Match") == et:
            self.send_response(304)
            self.send_header("ETag", et)
            self.end_headers()
            return
        resp_headers = [("Content-Type", ctype), ("ETag", et), ("Cache-Control", "no-cache")]
        if "gzip" in (self.headers.get("Accept-Encoding") or ""):
            data = gzip.compress(data, 6)
            resp_headers.append(("Content-Encoding", "gzip"))
        self.send_response(200)
        for k, v in resp_headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/" or p == "/index.html":
            self._serve_static("index.html", "text/html; charset=utf-8")
        elif p == "/app.css":
            self._serve_static("app.css", "text/css; charset=utf-8")
        elif p == "/app.js":
            self._serve_static("app.js", "application/javascript; charset=utf-8")
        elif p == "/manifest.json":
            self._serve_static("manifest.json", "application/manifest+json")
        elif p == "/apple-touch-icon.png":
            self._send(200, "image/png", _icon(180))
        elif p.startswith("/icon-") and p.endswith(".png") and p[6:-4].isdigit():
            self._send(200, "image/png", _icon(int(p[6:-4])))
        elif p == "/api/health":
            self._json(200, {"ok": True, "mock": CFG.get("mock", False)})
        elif p == "/deploy":
            tok = CFG.get("access_code") or ""
            q = parse_qs(urlparse(self.path).query)
            supplied = (q.get("token") or [""])[0]
            if not tok or not hmac.compare_digest(supplied, tok):
                return self._json(401, {"error": "token 不匹配"})
            self._trigger_deploy()
            self._json(200, {"ok": True, "msg": "部署已触发，约 10 秒后生效"})
        elif p == "/api/mockcfg":
            self._json(200, {"mock": bool(CFG.get("mock", False))})
        elif p == "/api/month":
            if not self._authed():
                return self._json(401, {"error": "需要访问码"})
            q = parse_qs(urlparse(self.path).query)
            user = (q.get("user") or ["beifeng"])[0]
            if user not in USERS:
                return self._json(400, {"error": "未知用户"})
            ym = (q.get("ym") or [""])[0]
            if not re.match(r"^\d{4}-\d{2}$", ym):
                return self._json(400, {"error": "ym 格式须为 YYYY-MM"})
            with db() as conn:
                rows = conn.execute(
                    "SELECT date, SUM(kcal) eaten, COUNT(*) n FROM meals"
                    " WHERE user_id=? AND date LIKE ? GROUP BY date ORDER BY date",
                    (user, ym + "%")).fetchall()
            self._json(200, {"ym": ym, "days": [
                {"date": r["date"], "eaten": r["eaten"] or 0, "n": r["n"]} for r in rows]})
        elif p == "/api/plan":
            if not self._authed():
                return self._json(401, {"error": "需要访问码"})
            q = parse_qs(urlparse(self.path).query)
            user = (q.get("user") or ["beifeng"])[0]
            if user not in USERS:
                return self._json(400, {"error": "未知用户"})
            self._json(200, load_plan(user) or {"days": []})
        elif p == "/api/workouts":
            if not self._authed():
                return self._json(401, {"error": "需要访问码"})
            q = parse_qs(urlparse(self.path).query)
            user = (q.get("user") or ["beifeng"])[0]
            if user not in USERS:
                return self._json(400, {"error": "未知用户"})
            wk = week_workouts(user)
            self._json(200, {"records": wk, "count": len(wk)})
        elif p.startswith("/photo/"):
            if not self._authed():
                return self._send(404, "image/jpeg", b"")
            try:
                rid = int(p.split("/")[2])
            except ValueError:
                return self._send(404, "text/plain", b"not found")
            # BUG-03：归属校验——?user= 需与记录的 user_id 一致
            q = parse_qs(urlparse(self.path).query)
            u = (q.get("user") or [""])[0]
            with db() as conn:
                row = conn.execute("SELECT user_id FROM meals WHERE id=?", (rid,)).fetchone()
            if row is None or (u and row["user_id"] != u):
                return self._send(404, "image/jpeg", b"")
            fp = os.path.join(DATA, "meals", "record_%d.jpg" % rid)
            if (q.get("thumb") or [""])[0] == "1":  # 列表48px缩略图：~8KB vs 原图100KB+
                tfp = os.path.join(DATA, "meals", "record_%d_thumb.jpg" % rid)
                if os.path.exists(tfp):
                    fp = tfp
            if not os.path.exists(fp):
                return self._send(404, "text/plain", b"not found")
            with open(fp, "rb") as f:
                self._send(200, "image/jpeg", f.read())
        elif p == "/api/today":
            if not self._authed():
                return self._json(401, {"error": "需要访问码"})
            q = parse_qs(urlparse(self.path).query)
            user = (q.get("user") or ["beifeng"])[0]
            if user not in USERS:
                return self._json(400, {"error": "未知用户"})
            date = (q.get("date") or [""])[0]
            if date and not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                return self._json(400, {"error": "日期格式不合法"})
            if date and date > datetime.now().strftime("%Y-%m-%d"):
                return self._json(400, {"error": "不能查看未来的记录"})
            self._json(200, today_summary(user, date or None))
        elif p == "/api/profile":
            if not self._authed():
                return self._json(401, {"error": "需要访问码"})
            q = parse_qs(urlparse(self.path).query)
            user = (q.get("user") or ["beifeng"])[0]
            if user not in USERS:
                return self._json(400, {"error": "未知用户"})
            with open(os.path.join(PROFILES_DIR, user + ".json"), encoding="utf-8") as f:
                self._json(200, json.load(f))
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        p = urlparse(self.path).path
        if p not in ("/api/meal", "/api/correct", "/api/profile", "/api/analyze", "/api/save", "/api/clear", "/api/mockcfg", "/deploy", "/api/plan", "/api/plan/parse", "/api/workouts"):
            return self._send(404, "text/plain", b"not found")
        if p == "/deploy":
            pass  # /deploy 有独立的 token 校验（Gitee Webhook 只带 X-Gitee-Token，不过通用门卫）
        elif not self._authed():
            return self._json(401, {"error": "需要访问码"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            if p == "/api/meal":
                return self._handle_meal(body)
            if p == "/api/correct":
                return self._handle_correct(json.loads(body.decode("utf-8")))
            if p == "/api/profile":
                return self._handle_profile(json.loads(body.decode("utf-8")))
            if p == "/api/analyze":
                return self._handle_analyze(json.loads(body.decode("utf-8")))
            if p == "/api/save":
                return self._handle_save(json.loads(body.decode("utf-8")))
            if p == "/api/clear":
                return self._handle_clear(json.loads(body.decode("utf-8")))
            if p == "/api/mockcfg":
                j = json.loads(body.decode("utf-8"))
                CFG["mock"] = bool(j.get("mock"))
                with open(CFG_PATH, "w", encoding="utf-8") as f:
                    json.dump(CFG, f, ensure_ascii=False, indent=2)
                self._json(200, {"ok": True, "mock": CFG["mock"]})
            if p == "/api/plan":
                j = json.loads(body.decode("utf-8"))
                user = j.get("user")
                if user not in USERS:
                    return self._json(400, {"error": "user 必须是 beifeng / gagayouna"})
                plan = j.get("plan") or {}
                if not isinstance(plan.get("days"), list) or not plan["days"]:
                    return self._json(400, {"error": "计划为空或格式不对"})
                for d in plan["days"]:
                    if d.get("dow") not in DOW:
                        return self._json(400, {"error": "dow 不合法：须为 周一~周日"})
                save_plan(user, plan)
                self._json(200, {"ok": True, "days": len(plan["days"])})
            if p == "/api/plan/parse":
                j = json.loads(body.decode("utf-8"))
                user = j.get("user")
                if user not in USERS:
                    return self._json(400, {"error": "user 必须是 beifeng / gagayouna"})
                text = (j.get("text") or "").strip()
                if not text:
                    return self._json(400, {"error": "粘贴计划文本"})
                llm = CFG.get("text_llm") or CFG["llm"]
                if not CFG.get("mock") and not llm.get("api_key"):
                    return self._json(503, {"error": "未配置 api_key"})
                res = llm_analyze(None, None, None,
                                  extra="\n计划文本：" + text,
                                  llm_cfg=llm, timeout=120, prompt=PLAN_PARSE_PROMPT)
                self._json(200, res)
            if p == "/deploy":
                tok = CFG.get("access_code") or ""
                supplied = self.headers.get("X-Gitee-Token") or self.headers.get("X-Access-Token") or ""
                if not tok or not hmac.compare_digest(supplied, tok):
                    return self._json(401, {"error": "token 不匹配"})
                ev = self.headers.get("X-Gitee-Event") or ""
                # Gitee 事件头实际值带 Hook 后缀（Tag Push Hook）；兼容旧式 tag_push
                if ev and "tag push" not in ev.lower() and ev != "tag_push":
                    return self._json(200, {"ok": True, "msg": "非 tag 事件，跳过部署", "event": ev})
                self._trigger_deploy()
                self._json(200, {"ok": True, "msg": "部署已触发"})
        except ApiError as ex:
            self._json(400, {"error": str(ex)})
        except Exception as ex:
            self._json(500, {"error": repr(ex)})

    def _handle_clear(self, j):
        """清空指定日期该用户全部记录（含照片文件，含训练记录）；缺省今天"""
        user = j.get("user")
        if user not in USERS:
            raise ApiError("user 必须是 beifeng / gagayouna")
        date = valid_date(j.get("date"))
        with db() as conn:
            rows = conn.execute("SELECT id FROM meals WHERE user_id=? AND date=?", (user, date)).fetchall()
            conn.execute("DELETE FROM meals WHERE user_id=? AND date=?", (user, date))
            conn.execute("DELETE FROM workouts WHERE user_id=? AND date=?", (user, date))
        for r in rows:
            for suffix in ("", "_thumb"):  # 原图+缩略图一起清
                try:
                    os.remove(os.path.join(DATA, "meals", "record_%d%s.jpg" % (r["id"], suffix)))
                except OSError:
                    pass
        self._json(200, {"ok": True, "cleared": len(rows)})

    def _handle_analyze(self, j):
        """只识别不入库：分析结果页专用。支持带 prev+修正文本/剩余照片的重新分析"""
        user = j.get("user")
        if user not in USERS:
            raise ApiError("user 必须是 beifeng / gagayouna")
        image = j.get("image")
        if not image:
            raise ApiError("需要照片")
        llm = CFG.get("llm", {})
        if not CFG.get("mock") and not llm.get("api_key"):
            raise ApiError("未配置 api_key：编辑 code/config.json 后重启（见 docs/05 §2）")
        fix = (j.get("text") or "").strip()
        prev = j.get("prev") or []
        if prev:
            extra = ("\n【当前待保存的识别结果】" + json.dumps(prev, ensure_ascii=False)
                     + "\n【用户修正要求】" + (fix or "（未写文字，看新照片）")
                     + "\n用户可能附上了新照片（如吃剩的盘子）：结合修正要求与新照片判断实际吃了多少，"
                       "需要扣回的输出负数项，输出完整的新 items，未提及的原有项保留。")
        else:
            extra = "\n用户拍摄了一张餐食照片，请识别其中全部食物。"
        res = llm_analyze(None, image, None, extra)
        items = [resolve_item(i, user) for i in (res.get("items") or [])]
        tg = profile_targets(user)
        s = today_summary(user)
        # 全天宏量 = 已入库合计 + 本次待保存餐（环形的"已吃"应包含眼前这顿）
        day = {"protein": s["protein"] + sum(i.get("protein_g") or 0 for i in items),
               "fat": s["fat"] + sum(i.get("fat_g") or 0 for i in items),
               "carb": s["carb"] + sum(i.get("carb_g") or 0 for i in items)}
        self._json(200, {"items": items,
                         "targets": {"protein": tg["protein"], "fat": tg["fat"], "carb": tg["carb"]},
                         "day": day})

    def _handle_save(self, j):
        """分析结果页确认保存：餐次用页面所选，items 用已识别结果"""
        user = j.get("user")
        if user not in USERS:
            raise ApiError("user 必须是 beifeng / gagayouna")
        mt = j.get("meal_type")
        if mt not in ("早餐", "午餐", "晚餐", "加餐"):
            raise ApiError("meal_type 不合法")
        items = j.get("items") or []
        if not items:
            raise ApiError("没有要保存的食物")
        for it in items:
            it["meal_type"] = mt
        ids = insert_meals(user, items, j.get("date"))
        img_b64 = j.get("image")  # 本次分析的照片存档 → 明细缩略图
        thumb_b64 = j.get("thumb")  # 前端canvas生成的240px缩略图（列表加载省流量）
        if img_b64:
            try:
                blob = base64.b64decode(img_b64)
                tblob = base64.b64decode(thumb_b64) if thumb_b64 else None
                for rid in ids:
                    with open(os.path.join(DATA, "meals", "record_%d.jpg" % rid), "wb") as f:
                        f.write(blob)
                    if tblob:
                        with open(os.path.join(DATA, "meals", "record_%d_thumb.jpg" % rid), "wb") as f:
                            f.write(tblob)
            except Exception:
                pass
        summary = today_summary(user)
        self._json(200, {"ok": True, "ids": ids, "eaten": summary["eaten"],
                         "remaining": summary["remaining"]})

    def _handle_profile(self, j):
        user = j.get("user")
        if user not in USERS:
            raise ApiError("user 必须是 beifeng / gagayouna")
        path = os.path.join(PROFILES_DIR, user + ".json")
        with open(path, encoding="utf-8") as f:
            p = json.load(f)
        name = (j.get("display_name") or "").strip()
        if name:
            p["display_name"] = name
        if j.get("gender") in ("male", "female"):
            p["gender"] = j["gender"]
        for k, v in (("age", num_field(j, "age", 10, 100, True)),
                     ("height_cm", num_field(j, "height_cm", 100, 250)),
                     ("weight_kg", num_field(j, "weight_kg", 30, 250)),
                     ("target_weight_kg", num_field(j, "target_weight_kg", 30, 250)),
                     ("training_days", num_field(j, "training_days", 0, 7, True)),
                     ("deficit", num_field(j, "deficit", 0, 750))):
            if v is not None:
                p[k] = v
        res = calc_plan(p["height_cm"], p["weight_kg"], p["age"], p["gender"],
                        p.get("goal", "fat_loss"), p.get("training_days", 4),
                        deficit=p.get("deficit"))
        p["targets"] = {"daily_kcal": res["target_kcal"], "protein_g": res["protein_g"],
                        "fat_g": res["fat_g"], "carb_g": res["carb_g"],
                        "calculated_by": "fitness_lib.py Mifflin-St Jeor",
                        "calculated_at": datetime.now().strftime("%Y-%m-%d")}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=2)
        self._json(200, {"ok": True, "targets": p["targets"]})

    def _trigger_deploy(self):
        """分离执行：git pull + 重启服务（先返回响应，1 秒后执行）。
        重启会终止本进程——由 systemd 自动拉起，属预期行为。"""
        cmd = ("sleep 1; cd /opt/fitness && git pull >> /opt/fitness/data/deploy.log 2>&1"
               " && systemctl restart fitness >> /opt/fitness/data/deploy.log 2>&1")
        subprocess.Popen(["bash", "-c", cmd], start_new_session=True)

    def _handle_meal(self, body: bytes):
        ctype = self.headers.get("Content-Type", "")
        user, text, image_b64, rec_date = None, "", None, None
        if "application/json" in ctype:
            j = json.loads(body.decode("utf-8"))
            user, text, image_b64 = j.get("user"), (j.get("text") or "").strip(), j.get("image")
            rec_date = j.get("date")
        else:
            fields, files = parse_multipart(ctype, body)
            user, text = fields.get("user"), fields.get("text", "")
            if files:
                image_b64 = base64.b64encode(files[0]).decode()
        if user not in USERS:
            return self._json(400, {"error": "user 必须是 beifeng / gagayouna"})
        if not text and not image_b64:
            return self._json(400, {"error": "需要照片或文字"})
        llm = CFG.get("llm", {})
        if not CFG.get("mock") and not llm.get("api_key"):
            return self._json(503, {"error": "未配置 api_key：编辑 code/config.json 填入后重启，或临时把 mock 设为 true"})
        pre = today_summary(user)
        recent = [{"id": r["id"], "meal_type": r["meal_type"], "food": r["food"], "kcal": r["kcal"]}
                  for r in pre["records"]][-5:]  # 上下文防重复，但不宜过长（思考型模型越慢）
        # 双通道：纯文字记录可走快模型（config.text_llm），拍照走主视觉模型
        # 快模型提取不到（复杂碎片输入）→ 自动升级 glm 主模型再判一次
        if not image_b64 and CFG.get("text_llm"):
            analysis = llm_analyze(text, None, recent, llm_cfg=CFG["text_llm"], timeout=90)
            if not (analysis.get("items") or []):
                analysis = llm_analyze(text, None, recent, timeout=120)
        else:
            analysis = llm_analyze(text, image_b64, recent)
        items = analysis.get("items") or []
        if not items:
            return self._json(200, {"reply": "🤔 没有需要新增的记录——可能这段内容都已经记过啦。可在下方明细核对；有漏掉的换个说法补充。", "items": []})

        # 更正路径：改写已有记录，不新增
        if analysis.get("action") == "correct":
            valid = {r["id"]: r for r in pre["records"]}
            cid = analysis.get("id")
            if cid in valid:
                it = resolve_item(items[0], user)
                if not it.get("meal_type"):
                    it["meal_type"] = valid[cid]["meal_type"]
                old_food = valid[cid]["food"]
                new_food = it.get("food", "")
                with db() as conn:
                    conn.execute(
                        "UPDATE meals SET food=?,meal_type=?,kcal=?,kcal_low=?,kcal_high=?,protein_g=?,note=? WHERE id=?",
                        (new_food, it["meal_type"], it.get("kcal"), it.get("kcal_low"),
                         it.get("kcal_high"), it.get("protein_g"), it.get("note", ""), cid))
                    # 扣回项跟随改名，保持一致性（红烧肉→回锅肉 时，扣回:红烧肉 → 扣回:回锅肉）
                    if old_food and new_food and old_food != new_food:
                        for pfx in ("扣回:", "扣回："):
                            conn.execute(
                                "UPDATE meals SET food=? WHERE user_id=? AND date=? AND food=?",
                                (pfx + new_food, user, pre["date"], pfx + old_food))
                summary = today_summary(user)
                reply = build_card([it], summary, verb="更正")
                if CFG.get("mock"):
                    reply += "\n⚠️ MOCK 测试模式：以上数值是假数据（接真模型见 docs/05 §2）"
                return self._json(200, {"reply": reply, "ids": [cid],
                                        "remaining": summary["remaining"], "eaten": summary["eaten"]})
            # id 无效 → 降级为普通记录

        # 训练路径：写 workouts 表（训练消耗已含在活动系数内，不进饮食额度）
        if analysis.get("action") == "training":
            date = datetime.now().strftime("%Y-%m-%d")
            ids, ek, names = [], 0, []
            with db() as conn:
                for it in items:
                    cur = conn.execute(
                        "INSERT INTO workouts (user_id,date,action,sets_reps,duration_min,est_kcal,note,created_at)"
                        " VALUES (?,?,?,?,?,?,?,?)",
                        (user, date, it.get("action", "训练"), it.get("sets_reps", ""),
                         it.get("duration_min"), it.get("kcal"), "训练记录",
                         datetime.now().isoformat(timespec="seconds")))
                    ids.append(cur.lastrowid)
                    ek += it.get("kcal") or 0
                    names.append((it.get("action") or "?") + " " + (it.get("sets_reps") or ""))
            reply = ("✅ 已记录训练：" + "、".join(n.strip() for n in names) +
                     "｜预计消耗 ≈" + str(ek) + " 千卡\n"
                     "💡 消耗已含在每日活动系数中，不从饮食额度扣除")
            hint = plan_hint(user, date)
            if hint:
                reply += "\n" + hint
            wk = week_workouts(user)
            reply += "\n🏋️ 本周已练 " + str(len(wk)) + " 次"
            return self._json(200, {"reply": reply, "ids": ids})

        items = [resolve_item(i, user) for i in items]
        rec_date = valid_date(rec_date)
        ids = insert_meals(user, items, rec_date)
        summary = today_summary(user, rec_date)  # 回显跟随记录日期，非固定今天
        reply = build_card(items, summary)
        if CFG.get("mock"):
            reply += "\n⚠️ MOCK 测试模式：以上数值是假数据（接真模型见 docs/05 §2）"
        self._json(200, {"reply": reply, "ids": ids,
                         "remaining": summary["remaining"], "eaten": summary["eaten"]})

    def _handle_correct(self, j):
        rid, action = j.get("id"), j.get("action")
        with db() as conn:
            if action == "delete":
                conn.execute("DELETE FROM meals WHERE id=?", (rid,))
                for suffix in ("", "_thumb"):  # 照片随记录一起删（含缩略图）
                    try:
                        os.remove(os.path.join(DATA, "meals", "record_%d%s.jpg" % (rid, suffix)))
                    except OSError:
                        pass
                return self._json(200, {"ok": True, "msg": "已删除"})
            if action == "edit":
                old = conn.execute("SELECT user_id,date,food FROM meals WHERE id=?", (rid,)).fetchone()
                sets, vals = [], []
                if j.get("food"):
                    sets.append("food=?"); vals.append(str(j["food"]).strip())
                if j.get("portion") is not None:
                    sets.append("portion=?"); vals.append(str(j["portion"]).strip())
                if j.get("kcal") is not None:
                    k = int(j["kcal"])
                    sets += ["kcal=?", "kcal_low=?", "kcal_high=?"]
                    vals += [k, int(k * 0.9), int(k * 1.1)]
                if j.get("protein_g") is not None:
                    sets.append("protein_g=?"); vals.append(int(j["protein_g"]))
                if j.get("meal_type") in ("早餐", "午餐", "晚餐", "加餐"):
                    sets.append("meal_type=?"); vals.append(j["meal_type"])
                if not sets:
                    return self._json(400, {"error": "没有要改的字段"})
                vals.append(rid)
                conn.execute("UPDATE meals SET " + ",".join(sets) + " WHERE id=?", vals)
                # BUG-04：改名时「扣回:xxx」伴生记录跟随（同 _handle_meal correct 分支）
                if old and j.get("food"):
                    old_food = old["food"]
                    new_food = str(j["food"]).strip()
                    if old_food and new_food and old_food != new_food:
                        for pfx in ("扣回:", "扣回："):
                            conn.execute(
                                "UPDATE meals SET food=? WHERE user_id=? AND date=? AND food=?",
                                (pfx + new_food, old["user_id"], old["date"], pfx + old_food))
                img = j.get("image")  # 编辑页可顺手换照片
                if img:
                    try:
                        with open(os.path.join(DATA, "meals", "record_%d.jpg" % rid), "wb") as f:
                            f.write(base64.b64decode(img))
                        th = j.get("thumb")
                        if th:
                            with open(os.path.join(DATA, "meals", "record_%d_thumb.jpg" % rid), "wb") as f:
                                f.write(base64.b64decode(th))
                    except Exception:
                        pass
                return self._json(200, {"ok": True, "msg": "已更正"})
        return self._json(400, {"error": "action 必须是 delete/edit"})

    def log_message(self, fmt, *args):
        pass


def parse_multipart(content_type, body: bytes):
    """极简 multipart 解析 → (fields:dict, files:list[bytes])"""
    fields, files = {}, []
    m = re.search(r'boundary="?([^;"]+)"?', content_type or "")
    if not m:
        return fields, files
    delim = b"--" + m.group(1).encode()
    for chunk in body.split(delim):
        chunk = chunk.strip(b"\r\n")
        if not chunk or chunk == b"--":
            continue
        head_end = chunk.find(b"\r\n\r\n")
        if head_end == -1:
            continue
        headers = chunk[:head_end].decode("latin1", "replace")
        content = chunk[head_end + 4:]
        nm = re.search(r'name="([^"]+)"(?:; filename="([^"]+)")?', headers)
        if not nm:
            continue
        name, filename = nm.group(1), nm.group(2)
        if filename:
            files.append(content)
        else:
            fields[name] = content.decode("utf-8", "replace").strip()
    return fields, files


def all_ips():
    ips = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.append(info[4][0])
    except Exception:
        pass
    return sorted(set(ips))


def main():
    init_db()
    port = int(os.environ.get("PORT") or CFG.get("port", 8124))
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port), H)
    except OSError as ex:
        print("端口被占用或无法绑定:", ex)
        sys.exit(1)
    mode = "MOCK（未接真实模型）" if CFG.get("mock") else "真实模型: " + CFG.get("llm", {}).get("model", "?")
    print("=" * 50)
    print("fitness v1 已启动 | 端口", port, "| 模式:", mode)
    for ip in all_ips():
        if not ip.startswith("127.") and not ip.endswith(".1"):
            print("  手机访问:  http://%s:%s" % (ip, port))
    print("  本机访问:  http://127.0.0.1:%s" % port)
    print("数据库:", DB_PATH)
    print("按 Ctrl+C 停止")
    print("=" * 50)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
