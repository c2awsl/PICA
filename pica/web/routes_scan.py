from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from pica.scanner import scan_progress, run_scan_in_thread

router = APIRouter()


@router.get("/scan", response_class=HTMLResponse)
async def scan_page(request: Request):
    cfg = request.app.state.cfg
    return request.app.state.templates.TemplateResponse(
        "scan.html",
        {"request": request, "cfg": cfg, "progress": scan_progress.snapshot()},
    )


@router.post("/scan/start")
async def scan_start(request: Request):
    cfg = request.app.state.cfg
    if scan_progress.running:
        return JSONResponse({"success": False, "error": "already running"})
    run_scan_in_thread(cfg)
    return JSONResponse({"success": True})


@router.post("/scan/stop")
async def scan_stop():
    scan_progress.set_running(False)
    return JSONResponse({"success": True})


@router.get("/scan/progress")
async def scan_progress_api():
    return JSONResponse(scan_progress.snapshot())
