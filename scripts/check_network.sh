#!/usr/bin/env bash
set -u

cd "$(dirname "$0")/.."

detect_windows_proxy_server() {
  if ! command -v powershell.exe >/dev/null 2>&1; then
    return
  fi

  powershell.exe -NoProfile -Command \
    "(Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings').ProxyServer" \
    2>/dev/null \
    | tr -d '\r' \
    | awk 'NF {print; exit}'
}

extract_port() {
  sed -nE 's/.*:([0-9]+).*/\1/p' | head -n 1
}

gateway="$(ip route | awk '/default/ {print $3; exit}')"
windows_proxy_server="$(detect_windows_proxy_server)"
detected_proxy_port="$(printf '%s' "${windows_proxy_server}" | extract_port)"
proxy_host="${CRAFT_PROXY_HOST:-${gateway}}"
proxy_port="${CRAFT_PROXY_PORT:-${detected_proxy_port:-7892}}"
proxy_url="${CRAFT_PROXY:-http://${proxy_host}:${proxy_port}}"

targets=(
  "https://github.com"
  "https://repo.anaconda.com/pkgs/main/noarch/repodata.json"
  "https://pypi.tuna.tsinghua.edu.cn/simple"
)

echo "WSL gateway: ${gateway:-unknown}"
echo "Windows proxy setting: ${windows_proxy_server:-not detected}"
echo "Proxy URL: ${proxy_url}"
echo

if command -v powershell.exe >/dev/null 2>&1; then
  echo "Windows listeners on proxy port ${proxy_port}:"
  powershell.exe -NoProfile -Command \
    "\$port = ${proxy_port}; Get-NetTCPConnection -State Listen | Where-Object {\$_.LocalPort -eq \$port} | Select-Object LocalAddress,LocalPort,OwningProcess | Format-Table -AutoSize" \
    2>/dev/null \
    | tr -d '\r'
  echo
fi

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
