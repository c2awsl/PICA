import re
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from pica.database import Image
from pica.thumbnail import generate_thumbnail

router = APIRouter()

THUMB_RE = re.compile(r"^/thumbnails/([a-f0-9]{32})_(\d+)\.jpg$")


@router.get("/thumbnails/{rest:path}")
async def serve_thumbnail(rest: str, request: Request):
    cfg = request.app.state.cfg
    match = THUMB_RE.match(f"/thumbnails/{rest}")
    if not match:
        return Response(status_code=404)

    md5_hash, size_str = match.group(1), match.group(2)
    thumb_path = cfg.thumbnails_dir / f"{md5_hash}_{size_str}.jpg"

    if thumb_path.exists():
        return FileResponse(str(thumb_path))

    engine = request.app.state.engine
    session = Session(bind=engine)
    try:
        img = session.execute(
            select(Image).where(Image.md5_hash == md5_hash)
        ).scalar_one_or_none()

        if img is None:
            return Response(status_code=404)

        source = None
        if img.pending_path and Path(img.pending_path).exists():
            source = img.pending_path
        elif img.archive_path and Path(img.archive_path).exists():
            source = img.archive_path
        elif img.filepath and Path(img.filepath).exists():
            source = img.filepath

        if not source:
            return Response(status_code=404)

        result = generate_thumbnail(source, md5_hash, cfg)
        if result and result.exists():
            return FileResponse(str(result))

        return Response(status_code=404)
    finally:
        session.close()
