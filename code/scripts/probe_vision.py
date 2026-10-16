# -*- coding: utf-8 -*-
"""probe_vision.py —— 探测网关视觉能力（用真实照片）。key 从 code/config.json 读取，不硬编码"""
import base64
import json
import os
import sys
import urllib.request

_cfg = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "code", "config.json"),
                      encoding="utf-8"))["llm"]
KEY = _cfg["api_key"]
BASE = _cfg["base_url"]
MODEL = _cfg["model"]
IMG = sys.argv[1] if len(sys.argv) > 1 else r"E:\SoftWare\AI\fitness\data\meals\probe_small.jpg"

with open(IMG, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

body = {
    "model": MODEL,
    "max_tokens": 500,
    "messages": [{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
            {"type": "text", "text": '识别这张图里的食物。只输出JSON：{"items":[{"food":"...","portion":"...","kcal":0,"kcal_low":0,"kcal_high":0,"protein_g":0}]}'},
        ],
    }],
}
req = urllib.request.Request(
    BASE + "/v1/messages", data=json.dumps(body).encode("utf-8"),
    headers={"Content-Type": "application/json", "x-api-key": KEY,
             "anthropic-version": "2023-06-01"})
try:
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.loads(r.read().decode("utf-8"))
    texts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    print("VISION_OK")
    print("".join(texts)[:600])
except urllib.error.HTTPError as e:
    print("HTTP", e.code)
    print(e.read().decode("utf-8", "replace")[:600])
