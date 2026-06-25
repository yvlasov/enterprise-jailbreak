
# enterprise-jailbreak

ARM64 Docker image with FortiClient and CheckPoint VPN support, dnsmasq, and Dante SOCKS5 proxy.

Related projects:
- [yvlasov/forti-cookie](https://github.com/yvlasov/forti-cookie) — Playwright/Chromium container that extracts the FortiGate SVPNCOOKIE

## Project structure

```
enterprise-jailbreak/
├── Dockerfile
├── Makefile
├── docker-compose.yml
├── .env.example
├── entrypoint.sh
├── procwatch/                       # ProcWatch — VPN process watchdog (API + web UI)
├── scripts/
│   ├── vpn-start-checkpoint.sh
│   ├── vpn-stop-checkpoint.sh
│   ├── vpn-start-forticlient.sh     # runs forti-cookie via host Docker, then openfortivpn
│   └── vpn-stop-forticlient.sh
└── config/                          # static templates — safe to mount :ro
    ├── dnsmasq.conf
    ├── danted.conf
    ├── procwatch-checkpoint.yaml
    ├── procwatch-forticlient.yaml
    └── proxy.pac                    # optional — served at http://localhost:8080/proxy.pac
```

At startup `entrypoint.sh` renders the relevant templates into `/run/` (substituting env vars)
and points daemons at the rendered copies. Files under `/config/` are never modified.

## Build

```bash
make help    # list available targets
make build
```

For FortiClient, also build the `forti-cookie` image on the host:

```bash
cd ../forti-cookie && docker build --platform linux/arm64 -t forti-cookie .
```

## Docker Compose (recommended)

```bash
cp .env.example .env   # fill in server/user values
mkdir secrets
echo -n 'your-ad-password' > secrets/checkpoint_vpn_password.txt
echo -n 'your-password'    > secrets/forti_vpn_password.txt

make run-checkpoint
# or
make run-forticlient
```

## docker run (quick test)

### CheckPoint VPN

Requires `NET_ADMIN` only.

```bash
docker run \
  --cap-add NET_ADMIN \
  -p 8080:8080 -p 1080:1080 \
  -e VPN_TYPE=checkpoint \
  -e CHECKPOINT_VPN_SERVER=your.checkpoint.server \
  -e CHECKPOINT_VPN_USER=your_username \
  -e CHECKPOINT_VPN_PASSWORD=your_password \
  enterprise-jailbreak
```

| Env var | Default | Description |
|---|---|---|
| `CHECKPOINT_VPN_SERVER` | — | CheckPoint server hostname/IP |
| `CHECKPOINT_VPN_USER` | — | Username |
| `CHECKPOINT_VPN_PASSWORD` | — | AD domain password (plain text; base64-encoded automatically) |
| `CHECKPOINT_VPN_LOGIN_TYPE` | `vpn_Indeed` | snx-rs login type |
| `CHECKPOINT_VPN_TUNNEL_TYPE` | `ssl` | Tunnel type |
| `CHECKPOINT_VPN_IGNORE_CERT` | `true` | Ignore server cert |
| `CHECKPOINT_VPN_HEALTH_IP` | `10.226.0.5` | IP to ping for health check |
| `CHECKPOINT_VPN_IFACE` | `snx-tun` | VPN tunnel interface |

### FortiClient VPN

Requires `NET_ADMIN` and the host Docker socket mount. The `yvlasov/forti-cookie` image is accessed
directly from the host daemon — no image loading step needed.

The host must have the `ppp` kernel module loaded and `/dev/ppp` device available.
For OrbStack on macOS, run once in the OrbStack VM:

```bash
orb sudo modprobe ppp
```

```bash
docker run \
  --cap-add NET_ADMIN \
  --device /dev/ppp \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -p 8080:8080 -p 1080:1080 \
  -e VPN_TYPE=forticlient \
  -e FORTI_VPN_HOST=your.fortigate.host \
  -e FORTI_VPN_USER='domain\username' \
  -e FORTI_VPN_PASSWORD=your_password \
  yvlasov/enterprise-jailbreak
```

| Env var | Default | Description |
|---|---|---|
| `FORTI_VPN_HOST` | — | FortiGate hostname |
| `FORTI_VPN_USER` | — | Username |
| `FORTI_VPN_PASSWORD` | — | Password |
| `FORTI_VPN_PORT` | `443` | FortiGate port |
| `FORTI_VPN_TRUSTED_CERT` | — | Trusted cert hash (optional) |
| `FORTI_VPN_HEALTH_IP` | `8.8.8.8` | IP to ping for health check |
| `FORTI_VPN_IFACE` | `ppp0` | VPN tunnel interface |

## ProcWatch config

Templates live in `/config/procwatch-checkpoint.yaml` and `/config/procwatch-forticlient.yaml`.
At startup the active template is copied to `/run/procwatch.yaml` with `__VPN_HEALTH_IP__`
replaced by `CHECKPOINT_VPN_HEALTH_IP` or `FORTI_VPN_HEALTH_IP` respectively,
and `PROCWATCH_CONFIG` is pointed there.

**CheckPoint** (`/config/procwatch-checkpoint.yaml`)
```yaml
proc:
  name: checkpoint-vpn
  start:
    command: "/opt/vpn/vpn-start-checkpoint.sh"
    arg_env: "CHECKPOINT_VPN_OTP"  # ProcWatch injects the /start arg as this env var
    timeout: 120
    ready_match: "Connected since"
    failure_match: "failed"
  stop:
    command: "/opt/vpn/vpn-stop-checkpoint.sh"
    timeout: 10
  health:
    command: "ping -c 1 -W 2 __VPN_HEALTH_IP__"
    interval: 30
    success_exit_code: 0
    consecutive_failures: 3
    session_ttl: 0
host: "0.0.0.0"
port: 8080
log_level: "info"
```

**FortiClient** (`/config/procwatch-forticlient.yaml`)
```yaml
proc:
  name: forticlient-vpn
  start:
    command: "/opt/vpn/vpn-start-forticlient.sh"
    timeout: 120              # script exits once tunnel confirmed or times out
    ready_match: "Tunnel is up"
    failure_match: "ERROR"
  stop:
    command: "/opt/vpn/vpn-stop-forticlient.sh"
    timeout: 10
  health:
    command: "ping -c 1 -W 2 __VPN_HEALTH_IP__"
    interval: 30
    success_exit_code: 0
    consecutive_failures: 3
    session_ttl: 0
host: "0.0.0.0"
port: 8080
log_level: "info"
```

Mount a custom template to override:
```bash
-v /path/to/my-procwatch.yaml:/config/procwatch-checkpoint.yaml:ro
```

## ProcWatch API

Web UI and API at `http://localhost:8080`.

```bash
# CheckPoint: OTP from Indeed app is passed as arg
curl -X POST http://localhost:8080/start -d '{"arg": "123456"}'

curl -X POST http://localhost:8080/stop
curl http://localhost:8080/status
curl http://localhost:8080/health   # 200 = RUNNING, 503 = otherwise
```

### Proxy Auto-Config (PAC)

If `/config/proxy.pac` exists, ProcWatch serves it at `http://localhost:8080/proxy.pac`
with the correct `application/x-ns-proxy-autoconfig` content type.
Returns 404 if the file is absent.

```bash
# mount your PAC file
-v /path/to/proxy.pac:/config/proxy.pac:ro
```

Point browsers or OS network settings to `http://<container-ip>:8080/proxy.pac`.

`CHECKPOINT_VPN_PASSWORD` is the AD domain password — provided in plain text,
base64-encoded automatically by the entrypoint before writing `snx-rs.conf`.
The OTP is supplied per-call via the `arg` field and injected as `CHECKPOINT_VPN_OTP`.

Set `START_DANTE=0` to skip starting Dante automatically.

## Config overrides

All files under `/config/` are templates — never modified at runtime, safe to mount `:ro`.
Rendered copies used by daemons are written to `/run/` on each startup.

```bash
-v /path/to/dnsmasq.conf:/config/dnsmasq.conf:ro
-v /path/to/danted.conf:/config/danted.conf:ro
-v /path/to/my-procwatch.yaml:/config/procwatch-checkpoint.yaml:ro
```

## SOCKS5 proxy

Dante listens on `:1080` and routes traffic through the VPN tunnel. Starts automatically once the VPN interface appears.

```bash
curl --proxy socks5h://localhost:1080 https://internal.example.com
```

Chrome extension for browser routing: [Proxy SwitchyOmega](https://chromewebstore.google.com/detail/proxy-switchyomega-v3/hihblcmlaaademjlakdpicchbjnnnkbo)
