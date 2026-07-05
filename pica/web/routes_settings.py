from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from pica.config import Config

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    cfg: Config = request.app.state.cfg
    return request.app.state.templates.TemplateResponse(
        "settings.html",
        {"request": request, "cfg": cfg, "saved": False, "needs_restart": None},
    )


@router.post("/settings", response_class=HTMLResponse)
async def settings_save(request: Request):
    cfg: Config = request.app.state.cfg
    form = await request.form()

    needs_restart = []

    old_host = cfg.host
    old_port = cfg.port

    cfg.ollama_url = form.get("ollama_url", cfg.ollama_url).rstrip("/")
    cfg.ai_model = form.get("ai_model", cfg.ai_model)
    cfg.ai_prompt = form.get("ai_prompt", cfg.ai_prompt)
    cfg.ai_timeout = int(form.get("ai_timeout", cfg.ai_timeout))

    new_categories = [c.strip() for c in form.get("categories", "").split(",") if c.strip()]
    cfg.categories = new_categories

    raw_sources = form.get("scan_sources", "")
    cfg.scan_sources = [s.strip() for s in raw_sources.split("\n") if s.strip()]

    host = form.get("host", str(cfg.host))
    port = int(form.get("port", cfg.port))
    if host != old_host or port != old_port:
        needs_restart.append("服务地址/端口")
    cfg.host = host
    cfg.port = port

    cfg.ensure_dirs()
    cfg.save()

    return request.app.state.templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "cfg": cfg,
            "saved": True,
            "needs_restart": needs_restart,
        },
    )
