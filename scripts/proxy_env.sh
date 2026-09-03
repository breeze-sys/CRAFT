#!/usr/bin/env bash

gateway="$(ip route | awk '/default/ {print $3; exit}')"
proxy_host="${CRAFT_PROXY_HOST:-${gateway}}"
proxy_port="${CRAFT_PROXY_PORT:-7892}"
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
echo
echo "Run this file with 'source scripts/proxy_env.sh' so exports affect your shell."

