from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from pica.database import ScanStatus, get_engine, get_session_factory

router = APIRouter()


def _read_progress(cfg) -> dict:
    engine = get_engine(cfg)
    sf = get_session_factory(engine)
    session = sf()
    try:
        def g(key, default="0"):
            row = session.get(ScanStatus, key)
            return row.value if row else default
        return {
            "running": g("running", "0") == "1",
            "found": int(g("found")),
            "new": int(g("new")),
            "skipped": int(g("skipped")),
            "errors": int(g("errors")),
            "current_file": g("current_file", ""),
            "current_source": g("current_source", ""),
        }
    finally:
        session.close()


def _write_command(cfg, cmd: str):
    engine = get_engine(cfg)
    sf = get_session_factory(engine)
    session = sf()
    try:
        row = session.get(ScanStatus, "command")
        if row:
            row.value = cmd
        else:
            session.add(ScanStatus(key="command", value=cmd))
        session.commit()
    finally:
        session.close()


@router.get("/scan", response_class=HTMLResponse)
async def scan_page(request: Request):
    cfg = request.app.state.cfg
    progress = _read_progress(cfg)
    return request.app.state.templates.TemplateResponse(
        "scan.html",
        {"request": request, "cfg": cfg, "progress": progress},
    )


@router.post("/scan/start")
async def scan_start(request: Request):
    cfg = request.app.state.cfg
    progress = _read_progress(cfg)
    if progress["running"]:
        return JSONResponse({"success": False, "error": "already running"})
    _write_command(cfg, "start")
    return JSONResponse({"success": True})


@router.post("/scan/stop")
async def scan_stop(request: Request):
    cfg = request.app.state.cfg
    _write_command(cfg, "stop")
    return JSONResponse({"success": True})


@router.get("/scan/progress")
async def scan_progress_api(request: Request):
    cfg = request.app.state.cfg
    return JSONResponse(_read_progress(cfg))


@router.post("/scan/exit")
async def scan_exit(request: Request):
    cfg = request.app.state.cfg
    _write_command(cfg, "exit")
    return JSONResponse({"success": True})
