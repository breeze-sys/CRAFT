#!/usr/bin/env bash

detect_windows_proxy_port() {
  if ! command -v powershell.exe >/dev/null 2>&1; then
    return
  fi

  powershell.exe -NoProfile -Command \
    "(Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings').ProxyServer" \
    2>/dev/null \
    | tr -d '\r' \
    | sed -nE 's/.*:([0-9]+).*/\1/p' \
    | head -n 1
}

gateway="$(ip route | awk '/default/ {print $3; exit}')"
detected_proxy_port="$(detect_windows_proxy_port)"
proxy_host="${CRAFT_PROXY_HOST:-${gateway}}"
proxy_port="${CRAFT_PROXY_PORT:-${detected_proxy_port:-7892}}"
proxy_url="${CRAFT_PROXY:-http://${proxy_host}:${proxy_port}}"

export HTTP_PROXY="${proxy_url}"
export HTTPS_PROXY="${proxy_url}"
export ALL_PROXY="${proxy_url}"
export http_proxy="${proxy_url}"
export https_proxy="${proxy_url}"
export all_proxy="${proxy_url}"

export PIP_PROXY="${proxy_url}"

echo "Proxy environment configured for this shell:"
echo "  HTTP_PROXY=${HTTP_PROXY}"
echo "  HTTPS_PROXY=${HTTPS_PROXY}"
echo "  ALL_PROXY=${ALL_PROXY}"
echo "  detected Windows proxy port: ${detected_proxy_port:-unknown}"
echo
echo "Run this file with 'source scripts/proxy_env.sh' so exports affect your shell."
