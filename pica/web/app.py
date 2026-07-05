from pathlib import Path

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates

from pica.config import Config
from pica.database import get_engine
from pica.web.routes_thumbnail import router as thumbnail_router
from pica.web.routes_pending import router as pending_router
from pica.web.routes_archive import router as archive_router
from pica.web.routes_stats import router as stats_router
from pica.web.routes_settings import router as settings_router
from pica.web.routes_scan import router as scan_router
from pica.web.routes_browse import router as browse_router
from pica.web.routes_tags import router as tags_router
from pica.web.routes_groups import router as groups_router
from pica.web.routes_categories import router as categories_router
from pica.web.routes_recycle import router as recycle_router
from pica.web.routes_boxes import router as boxes_router
from pica.web.routes_audit import router as audit_router

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

    app.include_router(thumbnail_router, prefix="")
    app.include_router(pending_router, prefix="")
    app.include_router(archive_router, prefix="")
    app.include_router(stats_router, prefix="")
    app.include_router(settings_router, prefix="")
    app.include_router(scan_router, prefix="")
    app.include_router(browse_router, prefix="")
    app.include_router(tags_router, prefix="")
    app.include_router(groups_router, prefix="")
    app.include_router(categories_router, prefix="")
    app.include_router(recycle_router, prefix="")
    app.include_router(boxes_router, prefix="")
    app.include_router(audit_router, prefix="")

    return app
