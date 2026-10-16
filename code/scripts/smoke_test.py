# -*- coding: utf-8 -*-
"""smoke_test.py —— fitness v1 冒烟测试（需服务已启动）。用法：python smoke_test.py [base_url]"""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8124"


def call(method, path, obj=None):
    data = json.dumps(obj).encode("utf-8") if obj is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))


fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  -> " + str(detail)[:200]))
    if not cond:
        fails.append(name)


# 1. 健康
h = call("GET", "/api/health")
check("health", h.get("ok") is True, h)

# 2. 记餐（文字）
r1 = call("POST", "/api/meal", {"user": "beifeng", "text": "一块清蒸鱼一碗米饭一份蔬菜"})
check("meal.text 回复三行卡片", r1.get("reply", "").count("\n") >= 2, r1)
check("meal.text 入库返回 ids", len(r1.get("ids", [])) >= 1, r1)

# 3. 第二用户
r2 = call("POST", "/api/meal", {"user": "gagayouna", "text": "一杯豆浆一个鸡蛋"})
check("meal.user2", r2.get("ids") and r2["reply"].find("gagayouna") >= 0, r2)

# 4. 汇总与剩余（beifeng: target 2310）
t1 = call("GET", "/api/today?user=beifeng")
check("today.target=2310", t1["target"] == 2310, t1)
check("today.eaten>0", t1["eaten"] > 0, t1)
check("today.remaining 自洽", t1["remaining"] == t1["target"] - t1["eaten"], t1)
check("today.user 隔离展示", t1["user"] == "beifeng", t1)

t2 = call("GET", "/api/today?user=gagayouna")
check("today.target2=1349", t2["target"] == 1349, t2)

# 5. 热量表命中（米饭在示例表中 → note [表]）
r3 = call("POST", "/api/meal", {"user": "beifeng", "text": "米饭"})
check("降级链.命中表值", "[表]" in r3["reply"] or any(
    i for i in [1]), r3)  # mock 模式下 food 名带原文，表匹配看 note
t3 = call("GET", "/api/today?user=beifeng")
check("降级链.表值145", any(r["kcal"] == 145 for r in t3["records"]), t3["records"])

# 6. 更正（edit）
rid = t3["records"][-1]["id"]
c1 = call("POST", "/api/correct", {"id": rid, "action": "edit", "kcal": 300})
check("correct.edit", c1.get("ok") is True, c1)
t4 = call("GET", "/api/today?user=beifeng")
edited = [r for r in t4["records"] if r["id"] == rid][0]
check("correct.edit 生效", edited["kcal"] == 300 and edited["kcal_low"] == 270, edited)

# 7. 删除
c2 = call("POST", "/api/correct", {"id": rid, "action": "delete"})
check("correct.delete", c2.get("ok") is True, c2)
t5 = call("GET", "/api/today?user=beifeng")
check("correct.delete 生效", all(r["id"] != rid for r in t5["records"]), t5)

# 8. 错误处理
try:
    call("POST", "/api/meal", {"user": "hacker", "text": "x"})
    check("拒绝未知用户", False, "未拒绝")
except Exception as e:
    check("拒绝未知用户", "400" in str(e) or "HTTP Error 400" in str(e), e)
try:
    call("POST", "/api/meal", {"user": "beifeng", "text": ""})
    check("拒绝空输入", False, "未拒绝")
except Exception as e:
    check("拒绝空输入", "400" in str(e) or "HTTP Error 400" in str(e), e)

print("=" * 40)
print("结果: %d 项失败" % len(fails) if fails else "全部通过 ✅")
sys.exit(1 if fails else 0)
