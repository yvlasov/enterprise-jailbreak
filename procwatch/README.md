# ProcWatch

Minimalist process watchdog controller. One instance per container, one managed process.

## Files

```
procwatch/
├── main.py           # FastAPI app + endpoints
├── manager.py        # state machine, health loop, subprocess management
├── config.py         # Pydantic config model + loader
├── templates/
│   └── index.html    # dark web UI (vanilla JS, no build step)
├── config.yaml       # example config — copy and edit per container
├── Dockerfile
└── requirements.txt
```

## API

| Method | Path        | Body                   | Description                        |
|--------|-------------|------------------------|------------------------------------|
| POST   | `/start`    | `{"arg": "123456"}`    | Start process; arg injected as env |
| POST   | `/stop`     | —                      | Stop process                       |
| POST   | `/restart`  | `{"arg": "123456"}`    | Stop then start                    |
| GET    | `/status`   | —                      | Full state JSON                    |
| GET    | `/health`   | —                      | 200 if RUNNING, 503 otherwise      |
| GET    | `/`         | —                      | Web UI                             |
| GET    | `/proxy.pac`| file:/config/proxy.pac | Proxy Auto Config script           |

## States

`STOPPED` → `STARTING` → `RUNNING` → `DEGRADED` → `STOPPED`  
`STARTING` → `FAILED`

## Config reference

```yaml
proc:
  name: my-proc

  start:
    command: "/path/to/start.sh"
    arg_env: "MY_ARG"        # env var name for user-supplied arg (TOTP etc.)
    timeout: 30              # seconds; -1 if process is long-running and match-based
    ready_match: "ready"     # stdout/stderr substring → RUNNING (omit = rely on exit code)
    failure_match: "error"   # stdout/stderr substring → FAILED

  stop:
    command: "/path/to/stop.sh"
    timeout: 10

  health:
    command: "ping -c 1 -W 2 10.0.0.1"
    interval: 30
    success_exit_code: 0
    success_string: ""       # optional: must appear in output
    failure_string: ""       # optional: presence → failure
    consecutive_failures: 3
    session_ttl: 7200        # 0 = disabled

host: "0.0.0.0"
port: 8080
log_level: "info"
```
