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
import json
import os
import re
import socket
import sqlite3
import sys
import urllib.request
from datetime import datetime
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
    with db() as conn:
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
    return {"kcal": int(t["daily_kcal"]), "protein": int(t["protein_g"]), "name": p["display_name"]}


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

def llm_analyze(text, image_b64, recent=None, extra="", llm_cfg=None, timeout=120):
    """识别食物+判断意图；mock 模式返回固定结果。协议按配置：openai(默认) / anthropic
    llm_cfg：可选的独立模型配置（文字通道快模型），缺省用主配置"""
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
        return _anthropic_analyze(text, image_b64, llm, ctx, timeout=timeout)
    content = []
    if image_b64:
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64," + image_b64}})
    content.append({"type": "text", "text": ANALYZE_PROMPT + ctx})
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


def _anthropic_analyze(text, image_b64, llm, extra="", timeout=120):
    """Anthropic /v1/messages 协议（如火山方舟 coding 网关）。
    用流式请求：思考型模型思考阶段持续吐 delta，连接不会因长时间无响应被网关掐掉
    （非流式在网关高峰会被掐 → 用户端 TimeoutError）。
    思考占满 max_tokens 导致正文为空 → 重试一次。"""
    content = []
    if image_b64:
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}})
    content.append({"type": "text", "text": ANALYZE_PROMPT + extra})
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

def insert_meals(user_id, items):
    date = datetime.now().strftime("%Y-%m-%d")
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


def today_summary(user_id):
    date = datetime.now().strftime("%Y-%m-%d")
    tgt = profile_targets(user_id)
    with db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT id,meal_type,food,kcal,kcal_low,kcal_high,protein_g,note,fat_g,carb_g,portion FROM meals"
            " WHERE user_id=? AND date=? ORDER BY id", (user_id, date))]
        for r in rows:
            r["photo"] = 1 if os.path.exists(os.path.join(DATA, "meals", "record_%d.jpg" % r["id"])) else 0
    eaten = sum(r["kcal"] or 0 for r in rows)
    protein = sum(r["protein_g"] or 0 for r in rows)
    remaining = tgt["kcal"] - eaten
    return {"user": user_id, "name": tgt["name"], "date": date, "records": rows,
            "eaten": eaten, "protein": protein,
            "target": tgt["kcal"], "protein_target": tgt["protein"],
            "remaining": remaining, "dinner_tip": dinner_tip(rows, remaining)}


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
        tip += "｜今天余量大，加餐/夜宵还有空间"
    return tip


def build_card(items, summary, verb="记录"):
    low = sum(i.get("kcal_low") or 0 for i in items)
    high = sum(i.get("kcal_high") or 0 for i in items)
    protein = sum(i.get("protein_g") or 0 for i in items)
    names = "、".join(i.get("food", "?") + (i.get("portion", "")) for i in items)
    mid = sum(i.get("kcal") or 0 for i in items)
    meal_type = items[0].get("meal_type") or infer_meal_type()
    return (f"✅ 已{verb}{meal_type}：{names}，约{mid}kcal（区间{low}~{high}）｜蛋白{protein}g\n"
            f"📊 {summary['name']}今日已吃 {summary['eaten']}/{summary['target']} kcal｜"
            f"蛋白 {summary['protein']}/{summary['protein_target']}g\n"
            f"🔜 剩余 {summary['remaining']} kcal")

# ---------------------------------------------------------------- 页面

INDEX = r"""<!doctype html><html lang="zh"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#16a34a">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>减肥管家</title>
<style>
 *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
 body{font-family:system-ui,-apple-system,"PingFang SC",sans-serif;max-width:430px;margin:0 auto;padding:14px 12px 30px;background:#eef1f4;color:#191c1f}
 .hd{display:flex;align-items:center;justify-content:space-between;margin:2px 2px 12px}
 .hd h1{font-size:18px;margin:0}
 .seg{display:flex;gap:6px}
 .seg button{padding:7px 12px;border:1px solid #d6dbdf;background:#fff;border-radius:999px;font-size:13px;color:#555}
 .seg button.on{background:#16a34a;border-color:#16a34a;color:#fff;font-weight:600}
 .card{background:#fff;border-radius:18px;padding:16px;box-shadow:0 2px 12px rgba(16,24,40,.06);margin-bottom:12px}
 .muted{color:#8a9299;font-size:12.5px}
 .gear{border:1px solid #d6dbdf;background:#fff;border-radius:999px;padding:7px 10px;font-size:14px}
 .grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
 .grid label{display:block;font-size:12px;color:#8a9299;margin-bottom:3px}
 .grid input,.grid select{width:100%;border:1.5px solid #dfe4e8;border-radius:10px;padding:9px 10px;font-size:14px;outline:none;background:#fafbfc}
 .grid input:focus,.grid select:focus{border-color:#16a34a;background:#fff}
 .save{width:100%;margin-top:12px;border:0;border-radius:12px;padding:12px;font-size:15px;font-weight:600;background:#16a34a;color:#fff}
 .mback{position:fixed;inset:0;background:rgba(15,23,32,.45);display:none;align-items:flex-start;justify-content:center;padding:36px 12px;z-index:50;overflow-y:auto}
 .modal{background:#fff;border-radius:18px;max-width:430px;width:100%;padding:16px;box-shadow:0 10px 40px rgba(0,0,0,.2)}
 .mhead{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
 .mhead b{font-size:16px}
 .mhead button{border:0;background:#f0f2f4;border-radius:8px;width:30px;height:30px;font-size:14px}
 .tabs{display:flex;gap:6px;margin-bottom:14px}
 .tabs button{flex:1;padding:9px;border:1px solid #d6dbdf;background:#fff;border-radius:10px;font-size:14px;color:#555}
 .tabs button.on{background:#16a34a;border-color:#16a34a;color:#fff;font-weight:600}
 .panel{display:none}.panel.on{display:block}
 #av{display:none;position:fixed;top:0;bottom:0;left:0;right:0;margin:0 auto;max-width:430px;background:#eef1f4;z-index:40;overflow-y:auto;padding-bottom:86px;border-left:1px solid #e3e7ea;border-right:1px solid #e3e7ea}
 .avbar{position:sticky;top:0;display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:#eef1f4;z-index:5}
 .avbar>button{border:0;background:#fff;border-radius:10px;font-size:14px}
 #avBack{width:34px;height:34px}
 #avMeal{padding:9px 16px;border-radius:999px;font-weight:600}
 #avmenu{position:fixed;top:56px;left:50%;transform:translateX(-50%);background:#fff;border-radius:12px;
  box-shadow:0 6px 24px rgba(0,0,0,.15);display:none;z-index:60;overflow:hidden}
 #avmenu button{display:block;width:100%;border:0;background:none;padding:11px 30px;font-size:14.5px}
 #avmenu button.on{background:#f0fdf4;color:#16a34a;font-weight:700}
 #avImg{width:100%;max-height:300px;object-fit:cover;display:block;background:#dde2e6}
 .avwrap{padding:12px}
 .avcard{background:#fff;border-radius:18px;padding:14px;box-shadow:0 2px 12px rgba(16,24,40,.06);margin-bottom:12px}
 .avitem{padding:9px 0;border-bottom:1px solid #f0f2f4;display:flex;justify-content:space-between;gap:8px;align-items:baseline}
 .avitem:last-child{border-bottom:0}
 .avname b{font-size:14.5px}
 .avk{color:#5c6670;white-space:nowrap;font-size:13px}
 .avbig{font-size:32px;font-weight:800;color:#16a34a;letter-spacing:-.5px}
 .avbig small{font-size:13px;color:#8a9299;font-weight:500;margin-left:2px}
 .avmacros{display:flex;margin-top:10px}
 .avmacros div{flex:1;text-align:center;border-right:1px solid #f0f2f4}
 .avmacros div:last-child{border-right:0}
 .avmacros i{font-style:normal;display:block;font-size:18px;font-weight:700}
 .avmacros span{font-size:11.5px;color:#8a9299}
 .avbtns{position:fixed;bottom:0;left:0;right:0;margin:0 auto;max-width:430px;display:flex;gap:9px;padding:10px 12px calc(10px + env(safe-area-inset-bottom));background:#fff;box-shadow:0 -2px 10px rgba(0,0,0,.06);z-index:45}
 #avFix:disabled,#avSave:disabled{opacity:.55}
 .fixerr{display:none;margin-top:8px;padding:8px 10px;background:#fef2f2;border-left:3px solid #ef4444;color:#991b1b;font-size:12.5px;border-radius:6px;word-break:break-all}
 .fixerr.show{display:block}
 #avFix{flex:1;background:#fff;border:1.5px solid #16a34a;color:#16a34a;border-radius:12px;padding:13px;font-size:15px;font-weight:600}
 #avSave{flex:2;background:#16a34a;color:#fff;border:0;border-radius:12px;padding:13px;font-size:15px;font-weight:600}
 #fixText{width:100%;height:110px;border:1.5px solid #dfe4e8;border-radius:12px;padding:12px;font-size:14px;resize:vertical;background:#fafbfc;outline:none;box-sizing:border-box}
 #fixText:focus{border-color:#16a34a;background:#fff}
 .fixcnt{text-align:right;font-size:12px;color:#8a9299;margin-top:4px}
 .fixphotoline{display:flex;align-items:center;gap:8px;margin-bottom:8px}
 #fixPhotoBtn{border:1.5px solid #dfe4e8;background:#fafbfc;border-radius:10px;padding:8px 10px;font-size:13px}
 #fixThumb{width:42px;height:42px;border-radius:8px;object-fit:cover}
 .avload{padding:14px 0;text-align:center;color:#5c6670;font-size:13.5px}
 /* ---- 编辑抽屉 & 删除确认 ---- */
 .mback.up{align-items:flex-end;padding:0}
 .sheet{background:#fff;border-radius:22px 22px 0 0;max-width:430px;width:100%;padding:16px 16px calc(16px + env(safe-area-inset-bottom));
  transform:translateY(100%);transition:transform .28s cubic-bezier(.2,.8,.2,1)}
 .mback.up.open .sheet{transform:translateY(0)}
 .etitle{text-align:center;font-size:16px;font-weight:700;margin-bottom:12px}
 .ehead{display:flex;align-items:center;gap:10px;margin-bottom:6px}
 .ethumb{width:56px;height:56px;border-radius:14px;object-fit:cover;background:#f0f2f4;cursor:pointer}
 .ethumb.ph{display:flex;align-items:center;justify-content:center;font-size:22px}
 .ehint{font-size:11.5px;color:#8a9299}
 .elabel{font-size:12.5px;color:#8a9299;margin:9px 2px 5px}
 .einput{width:100%;box-sizing:border-box;border:1.5px solid #dfe4e8;border-radius:12px;padding:11px 12px;font-size:14.5px;outline:none;background:#fafbfc}
 .einput:focus{border-color:#57b8f2;background:#fff}
 .pills{display:flex;gap:8px;flex-wrap:wrap}
 .pills button{padding:8px 16px;border-radius:999px;border:1.5px solid #dfe4e8;background:#fafbfc;font-size:13.5px;color:#555}
 .pills button.on{border-color:#57b8f2;background:#eaf6ff;color:#1d6fa5;font-weight:600}
 .ebtns{display:flex;gap:10px;margin-top:14px}
 .ebtns .ghost{flex:1;border:0;background:#f0f2f4;border-radius:12px;padding:12px;font-size:15px;color:#555}
 .ebtns .primary{flex:2;border:0;background:#1c7ed6;color:#fff;border-radius:12px;padding:12px;font-size:15px;font-weight:600}
 .ebtns .danger{background:#f87171}
 .dtext{text-align:center;font-size:14.5px;padding:6px 0 14px}
 @keyframes bump{30%{transform:scale(1.1);color:#16a34a}}
 .num.bump{animation:bump .5s}
 /* ===== 玻璃冰块主题（互联网清新）=====
    body.theme-glass 时整体覆盖为淡蓝渐变底 + 磨砂半透明卡片 + 冰蓝主色 */
 body.theme-glass{background:linear-gradient(165deg,#cfe6fb 0%,#e6f3fc 45%,#dceff5 100%);color:#203442}
 body.theme-glass .card,body.theme-glass .modal{background:rgba(255,255,255,.40);border:1px solid rgba(255,255,255,.70);
  box-shadow:0 8px 32px rgba(84,140,190,.16);backdrop-filter:blur(24px) saturate(1.6);-webkit-backdrop-filter:blur(24px) saturate(1.6)}
 body.theme-glass .hd h1{color:#1d3d54}
 body.theme-glass .muted{color:#7d95ad}
 body.theme-glass .num{color:#1d3d54}
 body.theme-glass .seg button{background:rgba(255,255,255,.45);border-color:rgba(255,255,255,.7);color:#4a6b80}
 body.theme-glass .seg button.on{background:linear-gradient(135deg,#3ea0ff,#6fc3ff);border-color:transparent;color:#fff}
 body.theme-glass .gear{background:rgba(255,255,255,.45);border-color:rgba(255,255,255,.7)}
 body.theme-glass .bar{background:rgba(255,255,255,.55)}
 body.theme-glass .bar i{background:linear-gradient(90deg,#57b8f2,#8fd3ff)}
 body.theme-glass .bar.warn i{background:linear-gradient(90deg,#f7b267,#f2884b)}
 body.theme-glass .sumline{color:#5f7d92}
 body.theme-glass .dinnerline{border-top:1px dashed rgba(255,255,255,.8);color:#6f8ba1}
 body.theme-glass input[type=text]{background:rgba(255,255,255,.5);border-color:rgba(255,255,255,.75);color:#203442}
 body.theme-glass input[type=text]:focus{border-color:#57b8f2;background:rgba(255,255,255,.75)}
 body.theme-glass .btnrow .photo{background:linear-gradient(135deg,#3ea0ff,#6fc3ff)}
 body.theme-glass .btnrow .send{background:linear-gradient(135deg,#2f9dd8,#5fb6e8)}
 body.theme-glass #reply.ok{background:rgba(255,255,255,.5);border-left-color:#57b8f2}
 body.theme-glass #reply.err{background:rgba(255,235,235,.55);border-left-color:#ef8a8a;color:#a04b4b}
 body.theme-glass #reply.wait{background:rgba(255,255,255,.4);border-left-color:rgba(255,255,255,.8);color:#5f7d92}
 body.theme-glass .spin{border-color:rgba(255,255,255,.9);border-top-color:#57b8f2}
 body.theme-glass .chip{background:rgba(190,228,255,.5);color:#2a7fb8}
 body.theme-glass .gsug{color:#7d95ad}
 body.theme-glass .gtot{color:#1d3d54}
 body.theme-glass .mrow{border-bottom:1px solid rgba(255,255,255,.55)}
 body.theme-glass .mmain{background:transparent}
 body.theme-glass .thumb{background:rgba(255,255,255,.6)}
 body.theme-glass .kcell{color:#7d95ad}
 body.theme-glass .kcell b{color:#1d3d54}
 body.theme-glass .delzone2{background:#f9a8a8}
 body.theme-glass .save{background:linear-gradient(135deg,#3ea0ff,#6fc3ff)}
 body.theme-glass .grid input,body.theme-glass .grid select{background:rgba(255,255,255,.5);border-color:rgba(255,255,255,.75);color:#203442}
 body.theme-glass .tabs button{background:rgba(255,255,255,.45);border-color:rgba(255,255,255,.7);color:#4a6b80}
 body.theme-glass .tabs button.on{background:linear-gradient(135deg,#3ea0ff,#6fc3ff);border-color:transparent;color:#fff}
 body.theme-glass .mback{background:rgba(120,160,190,.35);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px)}
 body.theme-glass .fixcnt{color:#7d95ad}
 body.theme-glass .fixerr{background:rgba(255,235,235,.6)}
 body.theme-glass #av{background:linear-gradient(165deg,#cfe6fb 0%,#e6f3fc 45%,#dceff5 100%);border-color:rgba(255,255,255,.4)}
 body.theme-glass .avbar{background:transparent}
 body.theme-glass #avBack,body.theme-glass #avMeal{background:rgba(255,255,255,.5)}
 body.theme-glass #avmenu{background:rgba(255,255,255,.75);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
 body.theme-glass #avmenu button.on{background:rgba(190,228,255,.6);color:#1d6fa5}
 body.theme-glass .avcard{background:rgba(255,255,255,.40);border:1px solid rgba(255,255,255,.70);
  backdrop-filter:blur(24px) saturate(1.6);-webkit-backdrop-filter:blur(24px) saturate(1.6)}
 body.theme-glass .avbig{color:#1d6fa5}
 body.theme-glass .avitem{border-bottom:1px solid rgba(255,255,255,.55)}
 body.theme-glass .avmacros div{border-right:1px solid rgba(255,255,255,.6)}
 body.theme-glass .avmacros i{color:#1d3d54}
 body.theme-glass .avbtns{background:rgba(255,255,255,.55);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px)}
 body.theme-glass #avFix{background:rgba(255,255,255,.5);border-color:#57b8f2;color:#1d6fa5}
 body.theme-glass #avSave{background:linear-gradient(135deg,#3ea0ff,#6fc3ff)}
 body.theme-glass #fixText{background:rgba(255,255,255,.5);border-color:rgba(255,255,255,.75);color:#203442}
 body.theme-glass .gcard{background:rgba(255,255,255,.40);border:1px solid rgba(255,255,255,.70);
  box-shadow:0 8px 32px rgba(84,140,190,.16);backdrop-filter:blur(24px) saturate(1.6);-webkit-backdrop-filter:blur(24px) saturate(1.6)}
 body.theme-glass .mrow{border-bottom:0;box-shadow:0 1px 6px rgba(84,140,190,.10)}
 body.theme-glass .mmain{background:rgba(255,255,255,.62);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
 body.theme-glass .gh-name{color:#1d3d54}
 body.theme-glass .gh-tot b{color:#1d3d54}
 body.theme-glass .gh-tot small{color:#7d95ad}
 body.theme-glass .gsug{color:#7d95ad}
 body.theme-glass .chev{color:#3ea0ff}
 body.theme-glass .msub{color:#7d95ad}
 body.theme-glass .sheet{background:rgba(246,250,253,.68);backdrop-filter:blur(24px) saturate(1.6);-webkit-backdrop-filter:blur(24px) saturate(1.6);border:1px solid rgba(255,255,255,.70)}
 body.theme-glass .einput{background:rgba(255,255,255,.6);border-color:rgba(255,255,255,.8)}
 body.theme-glass .pills button{background:rgba(255,255,255,.5);border-color:rgba(255,255,255,.8);color:#4a6b80}
 body.theme-glass .pills button.on{background:#eaf6ff;border-color:#57b8f2;color:#1d6fa5}
 body.theme-glass .ebtns .primary{background:linear-gradient(135deg,#3ea0ff,#6fc3ff)}
 body.theme-glass .ebtns .ghost{background:rgba(255,255,255,.5)}
 body.theme-glass .ebtns .danger{background:#f9a8a8}
 .num{font-size:34px;font-weight:800;letter-spacing:-.5px;margin:2px 0 10px}
 .num small{font-size:14px;color:#8a9299;font-weight:500;margin-left:3px}
 .dinnerline{display:none;margin-top:9px;padding-top:8px;border-top:1px dashed #e6eaed;font-size:12.5px;color:#8a9299}
 .dinnerline.show{display:block}
 .gcard{background:#fff;border-radius:18px;padding:14px;box-shadow:0 2px 12px rgba(16,24,40,.06);margin-bottom:12px}
 .ghead{display:flex;align-items:center;gap:8px;padding:0 2px 2px}
 .gh-emoji{font-size:18px}
 .gh-name{font-size:16px;font-weight:700}
 .gh-tot{margin-left:auto;text-align:right}
 .gh-tot small{display:block;color:#8a9299;font-size:11px;font-weight:400}
 .gh-tot b{font-size:15px}
 .gsug{font-size:12px;color:#8a9299;margin:0 2px 10px}
 .mrow{position:relative;overflow:hidden;border-radius:14px;margin-bottom:9px;box-shadow:0 1px 4px rgba(16,24,40,.05)}
 .mrow:last-child{margin-bottom:0}
 .dz{position:absolute;top:4px;bottom:4px;right:4px;width:70px;display:flex;align-items:center;justify-content:center;
  opacity:0;pointer-events:none;transition:opacity .18s}
 .mrow.open .dz{opacity:1;pointer-events:auto}
 .delzone2{width:100%;height:42px;border:0;background:#f8a8a8;color:#fff;font-size:13px;font-weight:600;border-radius:999px}
 .mmain{position:relative;display:flex;align-items:center;gap:10px;padding:8px;background:#fff;border-radius:14px;transition:transform .18s;touch-action:pan-y;user-select:none}
 .thumb{width:48px;height:48px;border-radius:12px;object-fit:cover;flex:none;background:#f0f2f4}
 .thumb.ph{display:flex;align-items:center;justify-content:center;font-size:20px}
 .mname{flex:1;font-size:14.5px;font-weight:600;min-width:0;word-break:break-all}
 .msub{font-size:11.5px;color:#8a9299;margin-top:2px;font-weight:400}
 .kcell{color:#8a9299;white-space:nowrap;font-size:13px;cursor:pointer}
 .kcell b{color:#191c1f;font-weight:600}
 .chev{color:#c3cad1;margin-left:4px;font-weight:700}
 .bar{height:9px;background:#edf0f2;border-radius:99px;overflow:hidden}
 .bar i{display:block;height:100%;width:0;border-radius:99px;background:linear-gradient(90deg,#22c55e,#16a34a);transition:width .5s}
 .bar.warn i{background:linear-gradient(90deg,#f59e0b,#ef4444)}
 .sumline{margin-top:9px;font-size:12.5px;color:#5c6670}
 input[type=text]{width:100%;border:1.5px solid #dfe4e8;border-radius:12px;padding:12px 13px;font-size:15px;outline:none;background:#fafbfc}
 input[type=text]:focus{border-color:#16a34a;background:#fff}
 .btnrow{display:flex;gap:9px;margin-top:11px}
 .btnrow button{flex:1;border:0;border-radius:12px;padding:13px;font-size:15px;font-weight:600;color:#fff;transition:opacity .2s}
 .btnrow button:disabled{opacity:.45}
 .photo{background:#16a34a}.send{background:#0e7490}
 #reply{margin-top:11px;border-radius:12px;padding:12px 13px;font-size:13.5px;line-height:1.75;white-space:pre-wrap;display:none}
 #reply.ok{display:block;background:#f0fdf4;border-left:3px solid #16a34a}
 #reply.err{display:block;background:#fef2f2;border-left:3px solid #ef4444;color:#991b1b}
 #reply.wait{display:block;background:#f8fafc;border-left:3px solid #cbd5e1;color:#475569}
 .spin{display:inline-block;width:13px;height:13px;border:2px solid #cbd5e1;border-top-color:#16a34a;border-radius:50%;vertical-align:-2px;margin-right:8px;animation:sp .8s linear infinite}
 @keyframes sp{to{transform:rotate(360deg)}}
 .chip{display:inline-block;background:#eef6ee;color:#15803d;border-radius:6px;padding:1px 6px;font-size:11px;margin-right:6px}
 .del{color:#dc2626;margin-left:6px}.edit{color:#2563eb}
 #toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);background:#111827;color:#fff;padding:9px 16px;border-radius:10px;font-size:13px;opacity:0;transition:opacity .3s;pointer-events:none;max-width:80vw}
 #toast.show{opacity:.92}
</style></head><body>
<div class="hd"><h1>🍱 减肥管家</h1>
 <div style="display:flex;gap:6px;align-items:center">
  <div class="seg"><button id="u1"></button><button id="u2"></button></div>
  <button class="gear" id="gear" title="身体档案设置">⚙️</button>
  <button class="gear" id="themeBtn" title="切换主题">🧊</button>
 </div></div>
<div class="card">
 <div class="muted">今日剩余</div>
 <div class="num"><span id="remain">–</span><small>kcal</small></div>
 <div class="bar" id="bar"><i></i></div>
 <div class="sumline" id="sumline"></div>
 <div class="dinnerline" id="dinner"></div></div>
<div class="card">
 <input type="text" id="text" placeholder="说一句吃了啥，如：早上吃了一根烤肠" autocomplete="off">
 <div class="btnrow">
  <button class="photo" id="bPhoto">📷 拍照记录</button>
  <button class="send" id="bSend">发送</button></div>
 <input type="file" id="photo" accept="image/*" capture="environment" style="display:none">
 <div id="reply"></div></div>
<div class="card"><div class="muted" style="margin-bottom:4px">今日明细 · 右侧点改 · 左滑删除</div><div id="list"></div></div>
<div id="av">
 <div class="avbar">
  <button id="avBack">‹</button>
  <button id="avMeal"></button>
  <div style="width:34px"></div>
 </div>
 <div id="avmenu"></div>
 <img id="avImg" alt="餐食照片">
 <div class="avwrap">
  <div class="avcard" id="avTot"></div>
  <div class="avcard" id="avItems"></div>
 </div>
 <div class="avbtns"><button id="avFix">✏️ AI 修正</button><button id="avSave">💾 保存记录</button></div>
</div>
<div class="mback" id="fixBack" style="display:none">
 <div class="modal">
  <div class="mhead"><b>AI 修正结果</b><button id="fixClose">✕</button></div>
  <div class="muted" style="margin-bottom:8px">例：图里的不是鸡蛋是鸭蛋｜只吃了一半，热量减半｜这是中午那盘的剩余，扣回</div>
  <div class="fixphotoline"><button type="button" id="fixPhotoBtn">📷 传吃剩的照片</button><img id="fixThumb" style="display:none" alt=""><span class="muted" id="fixPhotoHint">可选：拍剩余的盘子，AI 按图扣减</span></div>
  <input type="file" id="fixPhoto" accept="image/*" capture="environment" style="display:none">
  <textarea id="fixText" maxlength="200" placeholder="告诉 AI 需要修正的部分，会重新分析"></textarea>
  <div class="fixcnt" id="fixCnt">0/200</div>
  <button class="save" id="fixOk">确定</button>
  <div class="fixerr" id="fixErr"></div>
 </div></div>
<div class="mback" id="mback">
 <div class="modal">
  <div class="mhead"><b>设置</b><button id="mclose">✕</button></div>
  <div class="tabs"><button class="tab on" id="tProfile">👤 个人信息</button><button class="tab" id="tGeneral">⚙️ 通用</button></div>
  <div class="panel on" id="pProfile">
   <div class="muted" style="margin-bottom:9px">保存后自动按 Mifflin-St Jeor 重算热量线</div>
   <div class="grid">
    <div><label>名称</label><input type="text" id="s_name"></div>
    <div><label>性别</label><select id="s_gender"><option value="male">男</option><option value="female">女</option></select></div>
    <div><label>年龄</label><input type="number" id="s_age"></div>
    <div><label>身高 cm</label><input type="number" id="s_height"></div>
    <div><label>体重 kg</label><input type="number" step="0.1" id="s_weight"></div>
    <div><label>目标体重 kg</label><input type="number" step="0.1" id="s_targetw"></div>
    <div><label>周练天数</label><input type="number" min="0" max="7" id="s_days"></div>
   </div>
   <button class="save" id="s_save">💾 保存并重算</button>
   <div class="muted" id="s_hint" style="margin-top:9px"></div>
  </div>
  <div class="panel" id="pGeneral">
   <div class="muted" style="padding:26px 0;text-align:center">暂无可配置项，敬请期待</div>
  </div>
 </div></div>
<div class="mback up" id="editBack" style="display:none">
 <div class="sheet">
  <div class="mhead"><b>编辑食物</b><button id="eClose">✕</button></div>
  <div class="ehead">
   <img id="eThumb" class="ethumb" alt="" style="display:none">
   <div class="ethumb ph" id="eThumbPh">🍳</div>
   <div class="ehint">点头像可更换这张照片</div>
   <input type="file" id="ePhoto" accept="image/*" style="display:none">
  </div>
  <div class="elabel">食物名称</div>
  <input class="einput" id="eFood">
  <div class="elabel">食用克重（如 120g，可留空）</div>
  <input class="einput" id="ePortion">
  <div class="elabel">热量 kcal</div>
  <input class="einput" id="eKcal" type="number">
  <div class="elabel">蛋白 g（可选）</div>
  <input class="einput" id="eProtein" type="number">
  <div class="elabel">餐段</div>
  <div class="pills" id="ePills"></div>
  <div class="ebtns"><button class="ghost" id="eCancel">取消</button><button class="primary" id="eSave">保存修改</button></div>
 </div></div>
<div class="mback" id="delBack" style="display:none">
 <div class="modal" style="max-width:320px">
  <div class="etitle">确定删除这条食物记录吗？</div>
  <div class="ebtns"><button class="ghost" id="dCancel">取消</button><button class="primary danger" id="dOk">删除</button></div>
 </div></div>
<div id="toast"></div>
<script>
const $=id=>document.getElementById(id);
window.onerror=function(m){try{toast("页面错误:"+m);}catch(_){}};
let user=localStorage.getItem("fg_user")||"beifeng";
function paintSeg(){$("u1").classList.toggle("on",user==="beifeng");$("u2").classList.toggle("on",user==="gagayouna");}
$("u1").textContent="🧑 邶风";$("u2").textContent="👩 gagayouna";
$("u1").onclick=()=>{user="beifeng";localStorage.setItem("fg_user",user);paintSeg();clearReply();refresh();if($("mback").style.display==="flex")loadProfile();};
$("u2").onclick=()=>{user="gagayouna";localStorage.setItem("fg_user",user);paintSeg();clearReply();refresh();if($("mback").style.display==="flex")loadProfile();};
function clearReply(){const el=$("reply");el.className="";el.textContent="";}
function openSettings(){$("mback").style.display="flex";loadProfile();}
function closeSettings(){$("mback").style.display="none";}
$("gear").onclick=openSettings;
function applyTheme(t){document.body.classList.toggle("theme-glass",t==="glass");
 $("themeBtn").textContent=t==="glass"?"🌿":"🧊";localStorage.setItem("fg_theme",t);}
$("themeBtn").onclick=()=>applyTheme(localStorage.getItem("fg_theme")==="glass"?"warm":"glass");
applyTheme(localStorage.getItem("fg_theme")||"warm");
$("mclose").onclick=closeSettings;
$("mback").onclick=e=>{if(e.target.id==="mback")closeSettings();};
$("tProfile").onclick=()=>{$("tProfile").classList.add("on");$("tGeneral").classList.remove("on");
 $("pProfile").classList.add("on");$("pGeneral").classList.remove("on");};
$("tGeneral").onclick=()=>{$("tGeneral").classList.add("on");$("tProfile").classList.remove("on");
 $("pGeneral").classList.add("on");$("pProfile").classList.remove("on");};
async function loadProfile(){
 try{const p=await api("/api/profile?user="+user);
  $("s_name").value=p.display_name||"";$("s_gender").value=p.gender||"male";
  $("s_age").value=p.age??"";$("s_height").value=p.height_cm??"";
  $("s_weight").value=p.weight_kg??"";$("s_targetw").value=p.target_weight_kg??"";
  $("s_days").value=p.training_days??4;
  const t=p.targets||{};
  $("s_hint").textContent="当前热量线 "+(t.daily_kcal??"?")+" kcal / 蛋白 "+(t.protein_g??"?")+"g（"+(t.calculated_at||"")+" 算）";
 }catch(e){toast("读取档案失败："+e.message);}
}
$("s_save").onclick=async()=>{
 try{const j=await api("/api/profile",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({user:user,display_name:$("s_name").value,gender:$("s_gender").value,
   age:$("s_age").value,height_cm:$("s_height").value,weight_kg:$("s_weight").value,
   target_weight_kg:$("s_targetw").value,training_days:$("s_days").value})});
  const btn=user==="beifeng"?$("u1"):$("u2");
  btn.textContent=(user==="beifeng"?"🧑 ":"👩 ")+($("s_name").value.trim()||user);
  toast("已保存，热量线 "+j.targets.daily_kcal+" kcal / 蛋白 "+j.targets.protein_g+"g");
  $("s_hint").textContent="当前热量线 "+j.targets.daily_kcal+" kcal / 蛋白 "+j.targets.protein_g+"g（刚重算）";
  refresh();
 }catch(e){toast("保存失败："+e.message);}
};
paintSeg();
const esc=s=>String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
async function api(path,opts,tmo){const ctl=("AbortController"in window)?new AbortController():null;
 const to=ctl?setTimeout(()=>ctl.abort(),tmo||180000):null;
 try{const r=await fetch(path,Object.assign({},opts,ctl?{signal:ctl.signal}:{}));
  let j=null;try{j=await r.json()}catch(_){}
  if(!r.ok)throw new Error((j&&j.error)||("HTTP "+r.status));return j;}
 finally{if(to)clearTimeout(to);}}
let busy=false,timer=null;
function setLoading(msg){busy=true;$("bPhoto").disabled=true;$("bSend").disabled=true;
 const el=$("reply"),t0=Date.now();el.className="wait";
 el.innerHTML="<span class='spin'></span>"+msg+" <b id='el'></b>";
 timer=setInterval(()=>{const s=Math.round((Date.now()-t0)/1000);
  $("el").textContent=s+"s"+(s>12?" · 大图高峰会慢些":"");},500);}
function done(){busy=false;$("bPhoto").disabled=false;$("bSend").disabled=false;if(timer)clearInterval(timer);}
function showOk(t){done();const el=$("reply");el.className="ok";el.textContent=t;}
function showErr(t){done();const el=$("reply");el.className="err";el.textContent="❌ "+t;}
function toast(t){const el=$("toast");el.textContent=t;el.classList.add("show");
 setTimeout(()=>el.classList.remove("show"),2200);}
const MEAL_ORD={"早餐":0,"午餐":1,"晚餐":2,"加餐":3};
async function refresh(){
 try{const j=await api("/api/today?user="+user);
  $("remain").textContent=j.remaining;
  const pct=Math.min(100,j.target?j.eaten/j.target*100:0);
  const bar=$("bar");bar.classList.toggle("warn",pct>85);
  bar.firstElementChild.style.width=pct+"%";
  $("sumline").textContent="已吃 "+j.eaten+" / "+j.target+" kcal ｜ 蛋白 "+j.protein+" / "+j.protein_target+" g";
  const d=$("dinner");d.textContent=j.dinner_tip?("🌙 "+j.dinner_tip):"";d.classList.toggle("show",!!j.dinner_tip);
  _recs={};j.records.forEach(r=>_recs[r.id]=r);
  const RAT={"早餐":0.25,"午餐":0.35,"晚餐":0.30,"加餐":0.10};
  const sug=m=>{const t=(j.target||0)*(RAT[m]||0);
   return (Math.round(t*0.85/5)*5)+" ~ "+(Math.round(t*1.15/5)*5);};
  const recs=[...j.records].sort((a,b)=>(MEAL_ORD[a.meal_type]??9)-(MEAL_ORD[b.meal_type]??9));
  const groups=[];let cur=null;
  for(const r of recs){
   if(!cur||cur.m!==r.meal_type){cur={m:r.meal_type,items:[],tot:0};groups.push(cur);}
   cur.items.push(r);cur.tot+=r.kcal||0;
  }
  const GEMO={"早餐":"☀️","午餐":"🌤️","晚餐":"🌙","加餐":"🍪"};
  let h="";
  for(const g of groups){
   h+="<div class='gcard'><div class='ghead'>"+
    "<span class='gh-emoji'>"+(GEMO[g.m]||"🍽️")+"</span><span class='gh-name'>"+esc(g.m)+"</span>"+
    "<div class='gh-tot'><small>本餐合计</small><b>"+g.tot+" 千卡</b></div></div>"+
    "<div class='gsug'>热量建议："+sug(g.m)+" kcal</div>";
   for(const r of g.items){
    h+="<div class='mrow' data-id='"+r.id+"'>"+
     "<div class='dz'><button class='delzone2' data-del='"+r.id+"'>删除</button></div>"+
     "<div class='mmain'>"+
     (r.photo?"<img class='thumb' src='/photo/"+r.id+"' alt=''>":"<div class='thumb ph'>🍳</div>")+
     "<div class='mname'>"+esc(r.food)+"<div class='msub'>"+
     [r.portion,r.note].filter(Boolean).map(esc).join(" · ")+"</div></div>"+
     "<div class='kcell'><b>"+r.kcal+"</b> 千卡<span class='chev'>›</span></div></div></div>";
   }
   h+="</div>";
  }
  $("list").innerHTML=h||"<div class='muted' style='padding:8px 0'>还没有记录，开吃吧 🍚</div>";
  bindSwipe($("list"));
 }catch(e){toast("加载失败："+e.message);}
}
let openId=null,suppressClick=false,_recs={};
function closeOpen(exceptId){document.querySelectorAll("#list .mrow").forEach(row=>{
 if(+row.dataset.id!==exceptId){row.querySelector(".mmain").style.transform="";row.classList.remove("open");}});
 if(exceptId==null)openId=null;}
function bindSwipe(list){
 list.querySelectorAll(".mrow").forEach(row=>{
  const rid=+row.dataset.id,main=row.querySelector(".mmain");
  let sx=0,sy=0,drag=false,moved=false,cap=false;
  main.addEventListener("pointerdown",e=>{sx=e.clientX;sy=e.clientY;drag=true;moved=false;cap=false;main.style.transition="none";});
  main.addEventListener("pointermove",e=>{if(!drag)return;
   const dx=e.clientX-sx,dy=e.clientY-sy;
   if(!moved&&Math.abs(dx)>8&&Math.abs(dx)>Math.abs(dy)){
    moved=true;suppressClick=true;setTimeout(()=>suppressClick=false,350);
    try{main.setPointerCapture(e.pointerId);}catch(_){}}
   if(!moved)return;
   const base=openId===rid?-72:0;
   main.style.transform="translateX("+Math.max(-72,Math.min(0,base+dx))+"px)";});
  const end=e=>{if(!drag)return;drag=false;main.style.transition="";
   if(cap){try{main.releasePointerCapture(e.pointerId);}catch(_){}}
   if(!moved){if(openId===rid){main.style.transform="";openId=null;}return;}
   const t=(openId===rid?-72:0)+(e.clientX-sx);
   if(t<-36){closeOpen(rid);main.style.transform="translateX(-72px)";row.classList.add("open");openId=rid;}
   else{main.style.transform="";row.classList.remove("open");if(openId===rid)openId=null;}};
  main.addEventListener("pointerup",end);
  main.addEventListener("pointercancel",()=>{drag=false;main.style.transition="";
   main.style.transform=openId===rid?"translateX(-72px)":"";row.classList.toggle("open",openId===rid);});
  main.addEventListener("click",e=>{if(suppressClick||drag||moved)return;
   if(e.target.closest(".kcell"))openEdit(rid);});
  row.querySelectorAll(".delzone2").forEach(b=>b.addEventListener("click",()=>delId(rid)));
 });
}
async function sendText(){
 if(busy)return;
 const t=$("text").value.trim();if(!t)return;
 setLoading("识别中…");
 try{const j=await api("/api/meal",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({user:user,text:t})},240000);
  if(j.reply&&j.reply.indexOf("没识别出")>=0){showErr(j.reply);}else{showOk(j.reply);bump();refresh();}
  $("text").value="";
 }catch(e){showErr(friendly(e.message));}
}
function friendly(m){
 if(/timed out|abort/i.test(m))return "网关高峰无响应（已等待超时）。稍后重试；长语音建议拆成按餐短句，更快更稳";
 if(/api_key/i.test(m))return m;
 return m;
}
$("text").addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();sendText();}});
$("bSend").onclick=sendText;
$("bPhoto").onclick=()=>$("photo").click();
// ---- 分析结果页（照片专用：识别→修正→确认保存）----
const MEALS=["早餐","午餐","晚餐","加餐"];
let avItems=[],avB64=null,avMeal="早餐",avBusy=false;
$("avmenu").innerHTML=MEALS.map(m=>"<button data-m='"+m+"'>"+m+"</button>").join("");
function hourMeal(h){return h<10?"早餐":h<14?"午餐":h<17?"加餐":h<21?"晚餐":"加餐";}
function exifHour(buf){
 try{
  const v=new DataView(buf);
  if(v.byteLength<12||v.getUint16(0)!==0xFFD8)return null;
  let off=2;
  while(off+4<v.byteLength){
   if(v.getUint8(off)!==0xFF)break;
   const mk=v.getUint8(off+1),len=v.getUint16(off+2);
   if(mk===0xE1&&off+10<v.byteLength&&v.getUint32(off+4)===0x45786966)return tiffHour(off+10);
   off+=2+len;
  }
 }catch(e){}
 return null;
 function tiffHour(t){
  const le=v.getUint16(t)===0x4949;
  const g16=o=>v.getUint16(t+o,le),g32=o=>v.getUint32(t+o,le);
  let ifd=t+g32(4),ptr=0,hour=null;
  for(let pass=0;pass<2&&ifd;pass++){
   const n=g16(ifd);
   for(let i=0;i<n;i++){
    const en=ifd+2+i*12,tag=g16(en);
    if(pass===0&&tag===0x8769)ptr=g32(en+8);
    if(pass===1&&tag===0x9003){
     const s=t+g32(en+8);let dt="";
     for(let k=0;k<19;k++){const c=v.getUint8(s+k);if(c>=32)dt+=String.fromCharCode(c);}
     const m=dt.match(/\d{4}:\d{2}:\d{2} (\d{2}):(\d{2})/);
     if(m)hour=+m[1];
    }
   }
   ifd=pass===0&&ptr?t+ptr:null;
  }
  return hour;
 }
}
let avInt=null;
function avWait(msg){$("avItems").innerHTML="<div class='avload'><span class='spin'></span> "+msg+" <b id='avel'></b></div>";
 const t0=Date.now();if(avInt)clearInterval(avInt);
 avInt=setInterval(()=>{const el=$("avel");if(!el){if(avInt)clearInterval(avInt);return;}
  const s=Math.round((Date.now()-t0)/1000);el.textContent=s+"s"+(s>15?" · 网络高峰，再等等":"");},500);}
function avDone(){if(avInt)clearInterval(avInt);avInt=null;}
function avBusyUI(on){$("avFix").disabled=on;$("avSave").disabled=on;}
function renderAv(){
 avDone();
 $("avMeal").textContent="今天 "+avMeal+" ▼";
 $("avmenu").querySelectorAll("button").forEach(b=>b.classList.toggle("on",b.dataset.m===avMeal));
 const tot=k=>avItems.reduce((s,i)=>s+(i[k]||0),0);
 let h="";
 for(const it of avItems)h+="<div class='avitem'><div class='avname'><b>"+esc(it.food)+"</b> <span class='muted'>"+
  esc(it.portion||"")+"</span> "+esc(it.note||"")+"</div><div class='avk'>"+it.kcal+" 千卡</div></div>";
 $("avItems").innerHTML=h||"<div class='avload'><span class='spin'></span> 识别中…</div>";
 if(avItems.length){
  $("avTot").innerHTML="<div class='avbig'>"+tot("kcal")+" <small>千卡</small></div>"+
   "<div class='avmacros'><div><i>"+tot("protein_g")+"</i><span>蛋白 g</span></div>"+
   "<div><i>"+tot("fat_g")+"</i><span>脂肪 g</span></div><div><i>"+tot("carb_g")+"</i><span>碳水 g</span></div></div>";
 }else $("avTot").innerHTML="";
}
function closeAv(){$("av").style.display="none";avBusy=false;}
$("avBack").onclick=closeAv;
$("avMeal").onclick=e=>{e.stopPropagation();
 const m=$("avmenu");m.style.display=m.style.display==="block"?"none":"block";};
$("avmenu").addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;
 avMeal=b.dataset.m;renderAv();$("avmenu").style.display="none";});
document.addEventListener("click",e=>{if(!e.target.closest("#avmenu")&&!e.target.closest("#avMeal"))$("avmenu").style.display="none";});
$("avSave").onclick=async()=>{
 if(avBusy||!avItems.length)return;avBusy=true;
 try{
  await api("/api/save",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({user:user,meal_type:avMeal,items:avItems,image:avB64})});
  const kcal=avItems.reduce((s,i)=>s+(i.kcal||0),0);
  closeAv();toast((kcal<0?"已扣回 ":"已记录 ")+kcal+" 千卡");refresh();
 }catch(e){toast("保存失败："+e.message);}
 avBusy=false;
};
let fixB64=null;
$("avFix").onclick=()=>{if(avBusy||!avB64)return;
 fixB64=null;$("fixText").value="";$("fixCnt").textContent="0/200";
 $("fixThumb").style.display="none";$("fixPhotoHint").textContent="可选：拍剩余的盘子，AI 按图扣减";
 $("fixBack").style.display="flex";$("fixText").focus();};
$("fixClose").onclick=()=>$("fixBack").style.display="none";
$("fixText").addEventListener("input",e=>{$("fixCnt").textContent=e.target.value.length+"/200";});
$("fixPhotoBtn").onclick=()=>$("fixPhoto").click();
$("fixPhoto").addEventListener("change",async e=>{
 const f=e.target.files[0];e.target.value="";
 if(!f)return;
 try{
  const img=new Image();img.src=await new Promise((ok,no)=>{const fr=new FileReader();
   fr.onload=()=>ok(fr.result);fr.onerror=no;fr.readAsDataURL(f);});
  await new Promise(ok=>img.onload=ok);
  const cv=document.createElement("canvas"),s=Math.min(1,1024/Math.max(img.width,img.height));
  cv.width=img.width*s;cv.height=img.height*s;cv.getContext("2d").drawImage(img,0,0,cv.width,cv.height);
  fixB64=cv.toDataURL("image/jpeg",0.8).split(",")[1];
  const th=$("fixThumb");th.src="data:image/jpeg;base64,"+fixB64;th.style.display="block";
  $("fixPhotoHint").textContent="已附剩余照片 ✓";
 }catch(err){toast("读图失败："+err.message);}
});
$("fixOk").onclick=async()=>{
 const t=$("fixText").value.trim();
 if(!t&&!fixB64){toast("写修正内容或附剩余照片");return;}
 avBusy=true;$("fixOk").disabled=true;$("fixOk").textContent="分析中…";
 const fe=$("fixErr");fe.classList.remove("show");
 try{
  const j=await api("/api/analyze",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({user:user,image:fixB64||avB64,text:t,prev:avItems})},200000);
  avItems=j.items||[];renderAv();$("fixBack").style.display="none";
 }catch(e){
  fe.textContent="修正失败："+e.message+"（已识别结果未丢失，可重试或返回）";
  fe.classList.add("show");
 }
 $("fixOk").disabled=false;$("fixOk").textContent="确定";avBusy=false;
};
$("photo").addEventListener("change",async e=>{
 const f=e.target.files[0];e.target.value="";
 if(!f||avBusy)return;
 avBusy=true;
 try{
  const hr=exifHour(await f.arrayBuffer());
  avMeal=hr!=null?hourMeal(hr):hourMeal(new Date().getHours());
  const img=new Image();img.src=await new Promise((ok,no)=>{const fr=new FileReader();
   fr.onload=()=>ok(fr.result);fr.onerror=no;fr.readAsDataURL(f);});
  await new Promise(ok=>img.onload=ok);
  const cv=document.createElement("canvas"),s=Math.min(1,1024/Math.max(img.width,img.height));
  cv.width=img.width*s;cv.height=img.height*s;cv.getContext("2d").drawImage(img,0,0,cv.width,cv.height);
  avB64=cv.toDataURL("image/jpeg",0.8).split(",")[1];
  $("avImg").src="data:image/jpeg;base64,"+avB64;
  avItems=[];$("av").style.display="block";window.scrollTo(0,0);renderAv();
  avBusyUI(true);
  avWait("识别中");
  const j=await api("/api/analyze",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({user:user,image:avB64})},200000);
  avItems=j.items||[];renderAv();
  if(!avItems.length)$("avItems").innerHTML="<div class='avload'>🤔 没识别出食物：点「AI 修正」描述一下，或返回重拍</div>";
 }catch(err){avDone();toast("识别失败："+err.message);closeAv();}
 avBusyUI(false);avBusy=false;
});
// ---- 编辑抽屉 & 删除确认 ----
let editId0=null,editB64=null,editBusy=false,delId0=null;
function openEdit(id){
 const r=_recs[id];if(!r)return;editId0=id;editB64=null;
 if(r.photo){$("eThumb").src="/photo/"+id;$("eThumb").style.display="block";$("eThumbPh").style.display="none";}
 else{$("eThumb").style.display="none";$("eThumbPh").style.display="flex";}
 $("eFood").value=r.food;$("ePortion").value=r.portion||"";
 $("eKcal").value=r.kcal;$("eProtein").value=(r.protein_g==null?"":r.protein_g);
 $("ePills").innerHTML=MEALS.map(m=>"<button data-m='"+m+"' class='"+(m===r.meal_type?"on":"")+"'>"+m+"</button>").join("");
 $("ePills").querySelectorAll("button").forEach(b=>b.onclick=()=>{
  $("ePills").querySelectorAll("button").forEach(x=>x.classList.remove("on"));b.classList.add("on");});
 $("editBack").style.display="flex";requestAnimationFrame(()=>$("editBack").classList.add("open"));
}
function closeEdit(){$("editBack").classList.remove("open");setTimeout(()=>$("editBack").style.display="none",280);}
$("eClose").onclick=closeEdit;$("eCancel").onclick=closeEdit;
$("eThumb").onclick=()=>$("ePhoto").click();$("eThumbPh").onclick=()=>$("ePhoto").click();
$("ePhoto").addEventListener("change",async e=>{
 const f=e.target.files[0];e.target.value="";if(!f)return;
 try{
  const img=new Image();img.src=await new Promise((ok,no)=>{const fr=new FileReader();fr.onload=()=>ok(fr.result);fr.onerror=no;fr.readAsDataURL(f);});
  await new Promise(ok=>img.onload=ok);
  const cv=document.createElement("canvas"),s=Math.min(1,1024/Math.max(img.width,img.height));
  cv.width=img.width*s;cv.height=img.height*s;cv.getContext("2d").drawImage(img,0,0,cv.width,cv.height);
  editB64=cv.toDataURL("image/jpeg",0.8).split(",")[1];
  $("eThumb").src="data:image/jpeg;base64,"+editB64;$("eThumb").style.display="block";$("eThumbPh").style.display="none";
 }catch(err){toast("读图失败："+err.message);}
});
$("eSave").onclick=async()=>{
 if(editBusy)return;editBusy=true;$("eSave").disabled=true;$("eSave").textContent="保存中…";
 const meal=$("ePills").querySelector("button.on").dataset.m;
 const kcalV=$("eKcal").value;
 try{
  await api("/api/correct",{method:"POST",headers:{"Content-Type":"application/json"},
   body:JSON.stringify({id:editId0,action:"edit",
    food:$("eFood").value.trim()||undefined,kcal:kcalV===""?undefined:parseFloat(kcalV),
    portion:$("ePortion").value.trim(),protein_g:$("eProtein").value===""?undefined:parseFloat($("eProtein").value),
    meal_type:meal,image:editB64||undefined})},60000);
  closeEdit();bump();refresh();
 }catch(e){toast("保存失败："+e.message);}
 $("eSave").disabled=false;$("eSave").textContent="保存修改";editBusy=false;
};
function delId(id){delId0=id;$("delBack").style.display="flex";}
$("dCancel").onclick=()=>$("delBack").style.display="none";
$("dOk").onclick=async()=>{
 $("delBack").style.display="none";
 try{await api("/api/correct",{method:"POST",headers:{"Content-Type":"application/json"},
  body:JSON.stringify({id:delId0,action:"delete"})});toast("已删除");bump();refresh();}
 catch(e){toast("删除失败："+e.message);}
};
function bump(){const el=$("remain");el.classList.remove("bump");void el.offsetWidth;el.classList.add("bump");}
// 点空白处收起滑开的删除区
document.addEventListener("click",e=>{
 if(openId!==null&&!e.target.closest("#list")&&!e.target.closest(".mback")&&!e.target.closest(".modal")){
  closeOpen(null);}
});
refresh();
</script></body></html>"""

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
        return self.headers.get("X-Access-Token") == code

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/" or p == "/index.html":
            self._send(200, "text/html; charset=utf-8", INDEX.encode("utf-8"))
        elif p == "/api/health":
            self._json(200, {"ok": True, "mock": CFG.get("mock", False)})
        elif p.startswith("/photo/"):
            if not self._authed():
                return self._send(404, "image/jpeg", b"")
            try:
                rid = int(p.split("/")[2])
            except ValueError:
                return self._send(404, "text/plain", b"not found")
            fp = os.path.join(DATA, "meals", "record_%d.jpg" % rid)
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
            self._json(200, today_summary(user))
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
        if p not in ("/api/meal", "/api/correct", "/api/profile", "/api/analyze", "/api/save"):
            return self._send(404, "text/plain", b"not found")
        if not self._authed():
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
        except ApiError as ex:
            self._json(400, {"error": str(ex)})
        except Exception as ex:
            self._json(500, {"error": repr(ex)})

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
        self._json(200, {"items": items})

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
        ids = insert_meals(user, items)
        img_b64 = j.get("image")  # 本次分析的照片存档 → 明细缩略图
        if img_b64:
            try:
                blob = base64.b64decode(img_b64)
                for rid in ids:
                    with open(os.path.join(DATA, "meals", "record_%d.jpg" % rid), "wb") as f:
                        f.write(blob)
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
                     ("training_days", num_field(j, "training_days", 0, 7, True))):
            if v is not None:
                p[k] = v
        res = calc_plan(p["height_cm"], p["weight_kg"], p["age"], p["gender"],
                        p.get("goal", "fat_loss"), p.get("training_days", 4))
        p["targets"] = {"daily_kcal": res["target_kcal"], "protein_g": res["protein_g"],
                        "fat_g": res["fat_g"], "carb_g": res["carb_g"],
                        "calculated_by": "fitness_lib.py Mifflin-St Jeor",
                        "calculated_at": datetime.now().strftime("%Y-%m-%d")}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, indent=2)
        self._json(200, {"ok": True, "targets": p["targets"]})

    def _handle_meal(self, body: bytes):
        ctype = self.headers.get("Content-Type", "")
        user, text, image_b64 = None, "", None
        if "application/json" in ctype:
            j = json.loads(body.decode("utf-8"))
            user, text, image_b64 = j.get("user"), (j.get("text") or "").strip(), j.get("image")
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

        items = [resolve_item(i, user) for i in items]
        ids = insert_meals(user, items)
        summary = today_summary(user)
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
                try:
                    os.remove(os.path.join(DATA, "meals", "record_%d.jpg" % rid))  # 照片随记录一起删
                except OSError:
                    pass
                return self._json(200, {"ok": True, "msg": "已删除"})
            if action == "edit":
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
                img = j.get("image")  # 编辑页可顺手换照片
                if img:
                    try:
                        with open(os.path.join(DATA, "meals", "record_%d.jpg" % rid), "wb") as f:
                            f.write(base64.b64decode(img))
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
    port = int(CFG.get("port", 8124))
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
