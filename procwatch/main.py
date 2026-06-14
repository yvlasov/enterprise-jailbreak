from __future__ import annotations
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from config import load_config
from manager import ProcManager, State

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("procwatch")

cfg = load_config()
manager = ProcManager(cfg.proc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("ProcWatch starting — proc: %s", cfg.proc.name)
    yield
    logger.info("ProcWatch shutting down")


app = FastAPI(title="ProcWatch", lifespan=lifespan)


# ── request/response models ──────────────────────────────────────────────────

class StartRequest(BaseModel):
    arg: Optional[str] = None


class ActionResponse(BaseModel):
    ok: bool
    returncode: int
    output: str


class StatusResponse(BaseModel):
    name: str
    state: str
    uptime: Optional[float]
    uptime_human: Optional[str]
    ttl_remaining: Optional[float]
    last_health_check_ago: Optional[float]
    last_health_ok: bool
    consecutive_failures: int
    action_logs: dict


# ── helpers ──────────────────────────────────────────────────────────────────

def _fmt_uptime(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def _build_status() -> StatusResponse:
    st = manager.status()
    uptime_human = _fmt_uptime(st.uptime) if st.uptime is not None else None
    last_ago = None
    if st.last_health_check:
        last_ago = round(time.time() - st.last_health_check, 1)
    return StatusResponse(
        name=cfg.proc.name,
        state=st.state.value,
        uptime=round(st.uptime, 1) if st.uptime is not None else None,
        uptime_human=uptime_human,
        ttl_remaining=round(st.ttl_remaining, 1) if st.ttl_remaining is not None else None,
        last_health_check_ago=last_ago,
        last_health_ok=st.last_health_ok,
        consecutive_failures=st.consecutive_failures,
        action_logs=st.action_logs,
    )


# ── endpoints ────────────────────────────────────────────────────────────────

@app.post("/start", response_model=ActionResponse)
async def start(req: StartRequest = StartRequest()):
    result = await manager.start(arg=req.arg)
    return ActionResponse(
        ok=result.returncode == 0,
        returncode=result.returncode,
        output=result.combined,
    )


@app.post("/stop", response_model=ActionResponse)
async def stop():
    result = await manager.stop()
    return ActionResponse(
        ok=result.returncode == 0,
        returncode=result.returncode,
        output=result.combined,
    )


@app.post("/restart", response_model=ActionResponse)
async def restart(req: StartRequest = StartRequest()):
    result = await manager.restart(arg=req.arg)
    return ActionResponse(
        ok=result.returncode == 0,
        returncode=result.returncode,
        output=result.combined,
    )


@app.get("/status", response_model=StatusResponse)
async def status():
    return _build_status()


@app.get("/health")
async def health():
    st = manager.status()
    if st.state == State.RUNNING:
        return {"status": "ok"}
    raise HTTPException(status_code=503, detail=st.state.value)


@app.get("/output/stream")
async def output_stream():
    async def generate():
        async for line in manager.stream_live_output():
            yield f"data: {json.dumps(line)}\n\n"
        yield "data: \"[DONE]\"\n\n"
    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/", response_class=HTMLResponse)
async def ui():
    with open("templates/index.html") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=cfg.host,
        port=cfg.port,
        log_level=cfg.log_level,
    )
