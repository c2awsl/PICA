from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pica.config import Config
from pica.database import get_engine
from pica.web.routes_pending import router as pending_router
from pica.web.routes_archive import router as archive_router
from pica.web.routes_stats import router as stats_router
from pica.web.routes_settings import router as settings_router
from pica.web.routes_scan import router as scan_router
from pica.web.routes_browse import router as browse_router

TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_app(cfg: Config, worker=None, cfg_file_path: Path | None = None) -> FastAPI:
    engine = get_engine(cfg)

    app = FastAPI(title="PICA", version="0.1.0")

    app.state.cfg = cfg
    app.state.engine = engine
    app.state.worker = worker
    app.state.cfg_file_path = cfg_file_path

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    app.state.templates = templates

    app.mount("/thumbnails", StaticFiles(directory=str(cfg.thumbnails_dir)), name="thumbnails")

    app.include_router(pending_router, prefix="")
    app.include_router(archive_router, prefix="")
    app.include_router(stats_router, prefix="")
    app.include_router(settings_router, prefix="")
    app.include_router(scan_router, prefix="")
    app.include_router(browse_router, prefix="")

    return app
