from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable

from config import ProcConfig

logger = logging.getLogger("procwatch.manager")


class State(str, Enum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"
    FAILED = "FAILED"


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    combined: str

    def to_dict(self):
        return {
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "combined": self.combined,
        }


@dataclass
class ActionLog:
    action: str
    timestamp: float
    result: Optional[CommandResult] = None


@dataclass
class ManagerStatus:
    state: State
    uptime: Optional[float]
    ttl_remaining: Optional[float]
    last_health_check: Optional[float]
    last_health_ok: bool
    consecutive_failures: int
    action_logs: dict


async def _run_command(
    command: str,
    timeout: int,
    extra_env: Optional[dict] = None,
    ready_match: Optional[str] = None,
    failure_match: Optional[str] = None,
    on_line: Optional[Callable[[str], None]] = None,
) -> tuple[CommandResult, Optional[asyncio.subprocess.Process]]:
    import os
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    if timeout <= 0 and ready_match:
        # Long-running: stream stdout+stderr, return on match; process stays alive
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )

        lines: list[str] = []

        async def read_until_match() -> str:
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode(errors="replace")
                lines.append(line)
                if on_line:
                    on_line(line)
                if ready_match in line:
                    return "ready"
                if failure_match and failure_match in line:
                    return "failure"
            return "eof"

        try:
            reason = await read_until_match()
        except asyncio.CancelledError:
            proc.kill()
            raise

        combined = "".join(lines)

        if reason == "ready":
            return CommandResult(0, combined, "", combined), proc

        rc = proc.returncode if proc.returncode is not None else await proc.wait()
        return CommandResult(rc if rc is not None else 1, "", combined, combined), None

    # Short-lived: read both streams line-by-line until exit or timeout
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []

    async def read_stream(stream: asyncio.StreamReader, dest: list[str], prefix: str = ""):
        async for raw in stream:
            line = raw.decode(errors="replace")
            dest.append(line)
            if on_line:
                on_line(prefix + line)

    try:
        _timeout = timeout if timeout > 0 else None
        await asyncio.wait_for(
            asyncio.gather(
                read_stream(proc.stdout, stdout_lines),
                read_stream(proc.stderr, stderr_lines, "[stderr] "),
            ),
            timeout=_timeout,
        )
        await proc.wait()
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        msg = f"[timeout after {timeout}s]"
        if on_line:
            on_line(msg + "\n")
        return CommandResult(-1, "", msg, msg), None

    stdout = "".join(stdout_lines)
    stderr = "".join(stderr_lines)
    combined = stdout + ("\n--- stderr ---\n" + stderr if stderr else "")

    return CommandResult(
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        combined=combined.strip(),
    ), None


class ProcManager:
    def __init__(self, cfg: ProcConfig):
        self.cfg = cfg
        self._state = State.STOPPED
        self._started_at: Optional[float] = None
        self._last_health_check: Optional[float] = None
        self._last_health_ok: bool = False
        self._consecutive_failures: int = 0
        self._health_task: Optional[asyncio.Task] = None
        self._action_logs: dict[str, ActionLog] = {}
        self._lock = asyncio.Lock()
        self._running_proc: Optional[asyncio.subprocess.Process] = None
        # Live output streaming
        self._live_lines: list[str] = []
        self._live_done: bool = True

    # ── live output ──────────────────────────────────────────────────────────

    def _live_reset(self):
        self._live_lines = []
        self._live_done = False

    def _live_append(self, line: str):
        self._live_lines.append(line)

    def _live_finish(self):
        self._live_done = True

    async def stream_live_output(self):
        """Async generator — yields lines as they're produced by the running command."""
        idx = 0
        while True:
            while idx < len(self._live_lines):
                yield self._live_lines[idx]
                idx += 1
            if self._live_done and idx >= len(self._live_lines):
                break
            await asyncio.sleep(0.05)
        # Drain any final lines added after done flag
        while idx < len(self._live_lines):
            yield self._live_lines[idx]
            idx += 1

    # ── public API ──────────────────────────────────────────────────────────

    async def start(self, arg: Optional[str] = None) -> CommandResult:
        async with self._lock:
            if self._state in (State.RUNNING, State.STARTING):
                return CommandResult(0, "", "already running", "already running")
            self._set_state(State.STARTING)

        self._live_reset()

        extra_env = {}
        if arg and self.cfg.start.arg_env:
            extra_env[self.cfg.start.arg_env] = arg

        result, live_proc = await _run_command(
            self.cfg.start.command,
            self.cfg.start.timeout,
            extra_env=extra_env or None,
            ready_match=self.cfg.start.ready_match,
            failure_match=self.cfg.start.failure_match,
            on_line=self._live_append,
        )
        self._live_finish()
        self._log_action("start", result)

        async with self._lock:
            if live_proc is not None:
                self._running_proc = live_proc
                self._mark_running()
            elif result.returncode != 0:
                self._set_state(State.FAILED)
            else:
                if self.cfg.start.ready_match:
                    if self.cfg.start.ready_match in result.combined:
                        self._mark_running()
                    else:
                        self._set_state(State.FAILED)
                else:
                    self._mark_running()

        return result

    async def stop(self) -> CommandResult:
        async with self._lock:
            if self._state == State.STOPPED:
                return CommandResult(0, "", "already stopped", "already stopped")
            self._set_state(State.STOPPING)
            self._cancel_health_task()

        result, _ = await _run_command(self.cfg.stop.command, self.cfg.stop.timeout)
        self._log_action("stop", result)

        async with self._lock:
            if self._running_proc is not None:
                try:
                    self._running_proc.kill()
                except ProcessLookupError:
                    pass
                self._running_proc = None
            self._set_state(State.STOPPED)
            self._started_at = None
            self._consecutive_failures = 0

        return result

    async def restart(self, arg: Optional[str] = None) -> CommandResult:
        await self.stop()
        return await self.start(arg)

    def status(self) -> ManagerStatus:
        uptime = None
        ttl_remaining = None
        if self._started_at and self._state in (State.RUNNING, State.DEGRADED):
            uptime = time.time() - self._started_at
            if self.cfg.health.session_ttl > 0:
                ttl_remaining = max(0.0, self.cfg.health.session_ttl - uptime)

        return ManagerStatus(
            state=self._state,
            uptime=uptime,
            ttl_remaining=ttl_remaining,
            last_health_check=self._last_health_check,
            last_health_ok=self._last_health_ok,
            consecutive_failures=self._consecutive_failures,
            action_logs={k: {"action": v.action, "timestamp": v.timestamp,
                              "result": v.result.to_dict() if v.result else None}
                         for k, v in self._action_logs.items()},
        )

    # ── internals ───────────────────────────────────────────────────────────

    def _set_state(self, state: State):
        logger.info("state: %s → %s", self._state, state)
        self._state = state

    def _mark_running(self):
        self._set_state(State.RUNNING)
        self._started_at = time.time()
        self._consecutive_failures = 0
        self._cancel_health_task()
        self._health_task = asyncio.create_task(self._health_loop())

    def _cancel_health_task(self):
        if self._health_task and not self._health_task.done():
            self._health_task.cancel()

    def _log_action(self, action: str, result: CommandResult):
        self._action_logs[action] = ActionLog(action=action, timestamp=time.time(), result=result)

    async def _health_loop(self):
        cfg = self.cfg.health
        try:
            while True:
                await asyncio.sleep(cfg.interval)

                if self._running_proc is not None and self._running_proc.returncode is not None:
                    logger.warning("long-running process exited with rc=%d", self._running_proc.returncode)
                    async with self._lock:
                        self._running_proc = None
                        self._set_state(State.DEGRADED)
                    return

                if cfg.session_ttl > 0 and self._started_at:
                    if time.time() - self._started_at >= cfg.session_ttl:
                        logger.info("session TTL expired, stopping")
                        asyncio.create_task(self.stop())
                        return

                result, _ = await _run_command(cfg.command, timeout=max(cfg.interval - 1, 5))
                self._last_health_check = time.time()
                self._log_action("health", result)

                ok = result.returncode == cfg.success_exit_code
                if cfg.failure_string and cfg.failure_string in result.combined:
                    ok = False
                if cfg.success_string and cfg.success_string not in result.combined:
                    ok = False

                async with self._lock:
                    if ok:
                        self._last_health_ok = True
                        self._consecutive_failures = 0
                        if self._state == State.DEGRADED:
                            self._set_state(State.RUNNING)
                    else:
                        self._last_health_ok = False
                        self._consecutive_failures += 1
                        logger.warning("health fail %d/%d", self._consecutive_failures, cfg.consecutive_failures)
                        if self._consecutive_failures >= cfg.consecutive_failures:
                            self._set_state(State.DEGRADED)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("health loop error: %s", e)
