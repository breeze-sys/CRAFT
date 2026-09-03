# WSL Network And Proxy Setup

This project is currently developed inside WSL2. If `conda` or `pip` cannot reach package sources, first check whether WSL can access the Windows proxy.

## Current Diagnosis

Observed on this host:

1. WSL distro: Ubuntu 22.04 on WSL2.
2. Windows system proxy: `127.0.0.1:7892` or `127.0.0.1:7893`, depending on the proxy app state.
3. Proxy process: `ziyoumaoCore`.
4. WSL default gateway: `172.25.128.1`.
5. The proxy listens only on Windows `127.0.0.1:<proxy-port>`.
6. WSL cannot connect to `127.0.0.1:<proxy-port>`, `172.25.128.1:<proxy-port>`, or `host.docker.internal:<proxy-port>`.

That means package managers inside WSL currently have no usable proxy path. GitHub may still work because it can be handled by a different proxy or DNS rule, but `conda` and `pip` package-source domains are not guaranteed to follow the same path.

## Fix Path A: Enable LAN Access In The Windows Proxy App

In the Windows proxy app, enable the option usually named one of:

```text
Allow LAN
Allow connections from LAN
Bind address: 0.0.0.0
Mixed port listen address: 0.0.0.0
```

Keep the port as `7892` unless the app shows a different HTTP/Mixed proxy port.

Then, in WSL:

```bash
cd /home/breeze/my-project/CRAFT
source scripts/proxy_env.sh
bash scripts/check_network.sh
```

If the check passes, install dependencies:

```bash
conda env create -f environment-cn.yml
conda activate craft
python scripts/check_environment.py --full
```

## Fix Path B: Use The WSL Gateway Explicitly

If the proxy app is listening on all interfaces, WSL should usually reach it through the WSL gateway:

```bash
export CRAFT_PROXY_HOST="$(ip route | awk '/default/ {print $3; exit}')"
export CRAFT_PROXY_PORT=7892
source scripts/proxy_env.sh
```

This normally expands to:

```text
http://172.25.128.1:7892
```

## Fix Path C: Use Windows Firewall Rules

If the proxy app already listens on `0.0.0.0:7892` but WSL still cannot connect, allow inbound TCP traffic to the proxy port in Windows Defender Firewall.

PowerShell check:

```powershell
Get-NetTCPConnection -LocalPort 7892 -State Listen |
  Select-Object LocalAddress,LocalPort,OwningProcess
```

Expected good sign:

```text
LocalAddress LocalPort
------------ ---------
0.0.0.0           7892
```

If it still shows only `127.0.0.1`, the proxy app has not opened LAN access.

## Fix Path C2: Windows Port Proxy

If the proxy app cannot listen on `0.0.0.0`, use Windows port forwarding. Run PowerShell as Administrator:

```powershell
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=7899 connectaddress=127.0.0.1 connectport=7893
New-NetFirewallRule -DisplayName "WSL proxy 7899" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 7899
```

Then in WSL:

```bash
cd /home/breeze/my-project/CRAFT
CRAFT_PROXY_PORT=7899 source scripts/proxy_env.sh
bash scripts/check_network.sh
```

Use `connectport=7892` instead of `7893` if Windows currently reports `ProxyServer: 127.0.0.1:7892`.

## Fix Path D: Offline Or Semi-Offline Install

If proxy access cannot be fixed immediately, development is not blocked completely:

1. CRAFT's package skeleton, protocol models, tests, CLI tools and docs can be developed with the current `.venv`.
2. Dependencies already available in existing environments can be reused for temporary checks.
3. Missing packages such as Grid2Op and gmssl can be installed later once proxy/package-source access is fixed.
4. Another machine can download wheels or a packed conda environment and move them into WSL.

Useful offline pattern:

```bash
python -m pip download -r requirements-dev.txt -d wheelhouse
python -m pip install --no-index --find-links wheelhouse -r requirements-dev.txt
```

For conda, use `conda-pack` on a machine where the environment can be created, then unpack it inside WSL.

## Commands

Check direct and proxied network access:

```bash
bash scripts/check_network.sh
```

Set proxy environment variables for the current shell:

```bash
source scripts/proxy_env.sh
```

Override proxy host or port:

```bash
CRAFT_PROXY_HOST=172.25.128.1 CRAFT_PROXY_PORT=7892 source scripts/proxy_env.sh
```

The scripts auto-detect the Windows proxy port when possible, so the manual `CRAFT_PROXY_PORT` override is only needed for custom forwarding ports such as `7899`.
