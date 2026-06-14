from __future__ import annotations
import os
import yaml
from pydantic import BaseModel, Field
from typing import Optional


class StartConfig(BaseModel):
    command: str
    arg_env: Optional[str] = None          # env var name to inject user-supplied arg
    timeout: int = 30                       # seconds to wait for ready/failure signal
    ready_match: Optional[str] = None      # stdout/stderr substring → RUNNING
    failure_match: Optional[str] = None    # stdout/stderr substring → FAILED


class StopConfig(BaseModel):
    command: str
    timeout: int = 10


class HealthConfig(BaseModel):
    command: str                            # e.g. "ping -c 1 -W 2 10.0.0.1"
    interval: int = 30                      # seconds between checks
    success_exit_code: int = 0
    success_string: Optional[str] = None   # must appear in output to pass
    failure_string: Optional[str] = None   # if present in output → fail
    consecutive_failures: int = 3          # failures before DEGRADED
    session_ttl: int = 0                   # 0 = disabled; seconds until auto-stop


class ProcConfig(BaseModel):
    name: str
    start: StartConfig
    stop: StopConfig
    health: HealthConfig


class AppConfig(BaseModel):
    proc: ProcConfig
    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "info"


def load_config(path: Optional[str] = None) -> AppConfig:
    path = path or os.environ.get("PROCWATCH_CONFIG", "/etc/procwatch/config.yaml")
    with open(path) as f:
        raw = yaml.safe_load(f)
    return AppConfig(**raw)
