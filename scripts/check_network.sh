#!/usr/bin/env bash
set -u

cd "$(dirname "$0")/.."

gateway="$(ip route | awk '/default/ {print $3; exit}')"
proxy_host="${CRAFT_PROXY_HOST:-${gateway}}"
proxy_port="${CRAFT_PROXY_PORT:-7892}"
proxy_url="${CRAFT_PROXY:-http://${proxy_host}:${proxy_port}}"

targets=(
  "https://github.com"
  "https://repo.anaconda.com/pkgs/main/noarch/repodata.json"
  "https://pypi.tuna.tsinghua.edu.cn/simple"
)

echo "WSL gateway: ${gateway:-unknown}"
echo "Proxy URL: ${proxy_url}"
echo

echo "Proxy port check:"
if timeout 5 bash -c ": > /dev/tcp/${proxy_host}/${proxy_port}" 2>/dev/null; then
  echo "  ok      ${proxy_host}:${proxy_port}"
else
  echo "  missing ${proxy_host}:${proxy_port}"
fi
echo

for target in "${targets[@]}"; do
  echo "Direct: ${target}"
  if curl -4 -I --connect-timeout 5 --max-time 10 "${target}" >/dev/null 2>&1; then
    echo "  ok"
  else
    echo "  failed"
  fi

  echo "Proxy:  ${target}"
  if curl -I --proxy "${proxy_url}" --connect-timeout 5 --max-time 10 "${target}" >/dev/null 2>&1; then
    echo "  ok"
  else
    echo "  failed"
  fi
  echo
done

