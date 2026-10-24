#!/usr/bin/env bash
# 推送带重试: 代理/直连按探测结果切换。
#
# 坑(2026-10-25 实测): siliao 仓库 3.2GB, 一次 push 要传 2000+ 对象,
# 走 Clash 代理时连接经常被 reset(curl 55), push 卡到超时被杀。
# 代理可用性会**翻转**: 有时代理通直连不通, 有时直连通代理不通。
# 所以每次都先两条 curl 探路, 按结果选方式, 并用重试循环顶过多轮 reset。
set -u
cd /e/workspace/siliao 2>/dev/null || cd "E:/workspace/siliao"

BRANCH=$(git branch --show-current)
REMOTE=$(git remote get-url origin)
MAX=${MAX:-6}

probe() {
  # $1 = 代理地址(空串=直连)
  local p="$1"
  if [ -n "$p" ]; then
    curl -s -o /dev/null -w "%{http_code}" --max-time 12 -x "$p" https://github.com 2>/dev/null
  else
    curl -s -o /dev/null -w "%{http_code}" --max-time 12 https://github.com 2>/dev/null
  fi
}

PXY="http://127.0.0.1:7897"

for i in $(seq 1 "$MAX"); do
  c_p=$(probe "$PXY")
  c_d=$(probe "")
  echo "[try $i/$MAX] proxy=$c_p direct=$c_d  remote=$(git rev-parse --short HEAD)"
  if [ "$c_p" = "200" ] && [ "$c_d" != "200" ]; then
    MODE="proxy"; ARGS="-c http.proxy=$PXY -c https.proxy=$PXY"
  elif [ "$c_d" = "200" ] && [ "$c_p" != "200" ]; then
    MODE="direct"; ARGS="-c http.proxy= -c https.proxy="
  elif [ "$c_p" = "200" ]; then
    MODE="proxy"; ARGS="-c http.proxy=$PXY -c https.proxy=$PXY"
  else
    echo "  两路都不通, 等待 20s 后重试"
    sleep 20; continue
  fi
  echo "  -> 用 $MODE 推送"
  # HTTP/1.1 + 低速容忍: 代理下 HTTP/2 协商容易卡死
  timeout 300 git $ARGS -c http.version=HTTP/1.1 \
      -c http.lowSpeedLimit=500 -c http.lowSpeedTime=120 \
      -c http.postBuffer=524288000 \
      push --set-upstream origin "$BRANCH"
  rc=$?
  echo "  push rc=$rc"
  if [ $rc -eq 0 ]; then
    echo "[done] 推送成功"
    exit 0
  fi
  sleep 10
done

echo "[fail] $MAX 次重试后仍未推送成功"
exit 1
