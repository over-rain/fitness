# -*- coding: utf-8 -*-
"""
fitness 本地照片接收端 —— 零依赖 (仅 Python 标准库)
功能：
  GET  /           返回手机端上传页（可拍照/相册选图 + 备注）
  POST /upload     multipart/form-data 上传的照片 (field: photo) + 备注 (field: note)
保存到 data/meals/，并追加一条记录到 data/meal_log.jsonl。
监听 0.0.0.0，同一局域网内手机浏览器访问 http://<电脑IP>:8123 即可上传。
"""
import json
import os
import socket
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

PORT = 8123
# 仓库根 = code/ 的上一级；数据目录在 <根>\data\（代码与数据分离）
BASE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATA = os.path.join(BASE, "data")
MEALS = os.path.join(DATA, "meals")
MEAL_LOG = os.path.join(DATA, "meal_log.jsonl")
os.makedirs(MEALS, exist_ok=True)

# 允许的图片扩展名（最宽容，服务端不卡类型，靠浏览器端类型限制即可）
ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"}

INDEX = """<!doctype html><html lang="zh"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>上传吃的 🍽</title>
<style>
  body{font-family:system-ui;max-width:430px;margin:0 auto;padding:16px;background:#f6f7f9}
  h1{font-size:20px}
  .card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 1px 4px rgba(0,0,0,.08);margin-bottom:14px}
  input[type=file],textarea{width:100%;box-sizing:border-box;border:1px solid #ccc;border-radius:9px;padding:10px}
  textarea{height:64px;resize:vertical;margin-top:10px}
  button{width:100%;background:#2b8a3e;color:#fff;border:0;border-radius:9px;padding:13px;font-size:16px;margin-top:12px}
  #status{white-space:pre-wrap;font-size:14px;color:#333}
  #prev{margin-top:12px;font-size:13px;color:#888}
</style>
<div class="card">
  <h1>上传吃的 🍽</h1>
  拍一张今天吃的，填个备注（比如「早」「半碗饭」「少油」），传上来即可。
  <form id="f">
    <input type="file" id="photo" name="photo" accept="image/*" capture="environment" multiple>
    <textarea id="note" name="note" placeholder="备注：早/中/晚 或 大概份量"></textarea>
    <button type="submit">⬆ 上传</button>
  </form>
  <div id="status"></div>
  <div id="prev"></div>
</div>
<script>
const f=document.getElementById('f'), st=document.getElementById('status'), prev=document.getElementById('prev');
f.addEventListener('submit',async e=>{
  e.preventDefault();
  st.textContent='上传中…';
  const fd=new FormData();
  const files=document.getElementById('photo').files;
  if(!files.length){st.textContent='请先选一张照片';return}
  for(const f of files) fd.append('photo',f);
  fd.append('note', document.getElementById('note').value||'');
  try{
    const r=await fetch('/upload',{method:'POST',body:fd});
    const t=await r.text();
    st.textContent=t;
    loadPrev();
  }catch(err){st.textContent='上传失败：'+err}
  document.getElementById('note').value='';
  document.getElementById('photo').value='';
});
async function loadPrev(){
  try{const r=await fetch('/recent'); const j=await r.json();
    prev.textContent='今天已传 '+j.count+' 张：'+j.files.join('、');
  }catch(e){}
}
loadPrev();
</script>"""


def now_token():
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def all_ips():
    ips = []
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ips.append(info[4][0])
    except Exception:
        pass
    return sorted(set(ips))


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/" or p == "/index.html":
            self._send(200, "text/html; charset=utf-8", INDEX.encode("utf-8"))
        elif p == "/recent":
            files = [x for x in self._today_meals()]
            self._send(200, "application/json; charset=utf-8",
                       json.dumps({"count": len(files), "files": files}, ensure_ascii=False).encode("utf-8"))
        else:
            self._send(404, "text/plain", b"not found")

    def _today_meals(self):
        today = datetime.now().strftime("%Y-%m-%d")
        out = []
        try:
            for fn in sorted(os.listdir(MEALS)):
                if fn.startswith(today):
                    out.append(fn)
        except FileNotFoundError:
            pass
        return out

    def do_POST(self):
        if urlparse(self.path).path != "/upload":
            self._send(404, "text/plain", b"not found")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            files, note = parse_multipart(self.headers.get("Content-Type", ""), body)
            saved = []
            for data in files:
                ext = ".jpg"
                path = os.path.join(MEALS, now_token() + "_" + str(int(time.time())) + ext)
                with open(path, "wb") as fh:
                    fh.write(data)
                saved.append(os.path.basename(path))
            if saved:
                rec = {"time": datetime.now().isoformat(timespec="seconds"),
                       "files": saved, "note": note, "tally": None}
                with open(MEAL_LOG, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                msg = f"✅ 已上传 {len(saved)} 张。\n备注：{note or '（无）'}\n去 Claude 里说「分析今天的饭」即可看到预估热量和提醒。"
            else:
                msg = "⚠ 没收到照片内容，请重试。"
            self._send(200, "text/plain; charset=utf-8", msg.encode("utf-8"))
        except Exception as ex:
            self._send(500, "text/plain", ("服务端错误: " + repr(ex)).encode("utf-8"))

    def log_message(self, fmt, *args):  # 静默默认日志
        pass


def parse_multipart(content_type, body: bytes):
    """极简 multipart 解析，返回 (files:list[bytes], note:str)。"""
    files, note = [], ""
    if not content_type:
        return files, note
    parts = [p for p in content_type.split(";") if p.strip().startswith("boundary=")]
    if not parts:
        return files, note
    boundary = parts[0].split("=", 1)[1].strip().strip('"').encode()
    delim = b"--" + boundary
    chunks = body.split(delim)
    for chunk in chunks:
        if not chunk or chunk in (b"--", b"\r\n"):
            continue
        chunk = chunk.rstrip(b"\r\n")
        if not chunk.lstrip(b"--"):
            chunk = chunk.strip(b"--")
        header_end = chunk.find(b"\r\n\r\n")
        if header_end == -1:
            continue
        headers = chunk[:header_end].decode("latin1", "replace")
        content = chunk[header_end + 4:]
        content = content.rstrip(b"\r\n")
        name_field, filename = header_file_info(headers)
        if filename is not None and name_field == "photo":
            files.append(content)
        elif name_field == "note":
            note = content.decode("utf-8", "replace").strip()
    return files, note


def header_file_info(headers: str):
    """从 part 头部提取 name 和 filename。"""
    name = None
    filename = None
    disp = ""
    for line in headers.split("\r\n"):
        low = line.lower()
        if disp == "" and low.startswith("content-disposition"):
            disp = line
    # 解析 content-disposition
    params = disp.split(";")
    for p in params[1:]:
        if "=" in p:
            k, v = p.strip().split("=", 1)
            v = v.strip().strip('"')
            if k == "name":
                name = v
            elif k == "filename":
                filename = v
    return name, filename


def main():
    try:
        server = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    except OSError as ex:
        print("端口被占用或无法绑定:", ex)
        sys.exit(1)
    print("=" * 46)
    print("fitness 接收端已启动，端口", PORT)
    for ip in all_ips():
        if not ip.startswith("127.") and not ip.endswith(".1"):
            print("  手机访问:  http://%s:%s" % (ip, PORT))
    print("保存在:", MEALS)
    print("按 Ctrl+C 停止。电脑不关机的期间让它一直跑着即可。")
    print("=" * 46)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()