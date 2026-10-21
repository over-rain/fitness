#!/bin/bash
# update.sh —— VPS 上更新减肥管家到最新代码并重启服务
# 用法：bash /opt/fitness/code/scripts/update.sh
set -e
cd /opt/fitness
echo "== 拉取最新代码 =="
git pull
echo "== 重启服务 =="
systemctl restart fitness
sleep 2
echo "== 健康检查 =="
curl -s -o /dev/null -w "首页: %{http_code}\n" http://127.0.0.1:80/
curl -s http://127.0.0.1:80/api/health
echo ""
echo "== 完成 =="
