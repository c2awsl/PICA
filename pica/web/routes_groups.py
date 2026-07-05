from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from pica.database import Image, ImageStatus, SimilarGroup, log_action

router = APIRouter()


def get_db(request: Request) -> Session:
    engine = request.app.state.engine
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()


@router.get("/groups", response_class=HTMLResponse)
async def groups_page(request: Request, db: Session = Depends(get_db)):
    show_processed = request.query_params.get("processed", "0") == "1"
    query = select(SimilarGroup)
    if not show_processed:
        query = query.where(SimilarGroup.processed == 0)
    query = query.order_by(SimilarGroup.created_at.desc())

    groups = db.execute(query).scalars().all()

    group_data = []
    for g in groups:
        images = db.execute(
            select(Image).where(Image.similar_group_id == g.id).limit(5)
        ).scalars().all()
        total = db.execute(
            select(func.count(Image.id)).where(Image.similar_group_id == g.id)
        ).scalar() or 0
        statuses = db.execute(
            select(Image.status, func.count(Image.id).label("cnt"))
            .where(Image.similar_group_id == g.id)
            .group_by(Image.status)
        ).all()
        group_data.append({
            "group": g,
            "images": images,
            "total": total,
            "statuses": {s.status.value: s.cnt for s in statuses},
        })

    return request.app.state.templates.TemplateResponse(
        "groups.html",
        {"request": request, "group_data": group_data, "show_processed": show_processed},
    )


@router.get("/groups/{group_id}", response_class=HTMLResponse)
async def group_detail(request: Request, group_id: int, db: Session = Depends(get_db)):
    g = db.get(SimilarGroup, group_id)
    if not g:
        return HTMLResponse("Not found", status_code=404)
    images = db.execute(
        select(Image).where(Image.similar_group_id == group_id)
    ).scalars().all()
    return request.app.state.templates.TemplateResponse(
        "group_detail.html",
        {"request": request, "group": g, "images": images},
    )


@router.get("/groups/{group_id}/suggest-keep")
async def suggest_keep(group_id: int, db: Session = Depends(get_db)):
    """Suggest which image to keep (highest resolution)."""
    images = db.execute(
        select(Image).where(Image.similar_group_id == group_id)
    ).scalars().all()
    if not images:
        return JSONResponse({"error": "no images"}, status_code=404)

    best = max(images, key=lambda x: (x.width or 0) * (x.height or 0))
    return JSONResponse({
        "suggested_id": best.id,
        "reason": f"最高分辨率 ({best.width}×{best.height})",
    })


@router.post("/groups/{group_id}/process")
async def process_group(request: Request, group_id: int, db: Session = Depends(get_db)):
    """Keep selected images, reject the rest, mark group as processed."""
    g = db.get(SimilarGroup, group_id)
    if not g:
        return JSONResponse({"error": "not found"}, status_code=404)

    form = await request.form()
    keep_ids = set()
    raw = form.get("keep_ids", "")
    if raw:
        keep_ids = set(int(x) for x in raw.split(",") if x.strip())

    images = db.execute(
        select(Image).where(Image.similar_group_id == group_id)
    ).scalars().all()

    for img in images:
        if img.id in keep_ids:
            continue
        # Reject non-kept images
        if img.status == ImageStatus.PENDING:
            img.status = ImageStatus.REJECTED
            from pica.archiver import cleanup_pending
            if img.pending_path:
                cleanup_pending(img.pending_path)

    g.processed = 1
    for img in images:
        img.processed_at = datetime.utcnow()
    log_action(db, "group_process", group_id, f"处理相似组: keep={keep_ids}")
    db.commit()

    ref = request.headers.get("Referer", "/groups")
    return RedirectResponse(url=ref, status_code=303)


@router.post("/groups/{group_id}/remove-image")
async def remove_image_from_group(request: Request, group_id: int, db: Session = Depends(get_db)):
    """Remove an image from a similar group (false positive)."""
    g = db.get(SimilarGroup, group_id)
    if not g:
        return JSONResponse({"error": "not found"}, status_code=404)

    form = await request.form()
    image_id = int(form.get("image_id", "0"))
    img = db.get(Image, image_id)
    if not img:
        return JSONResponse({"error": "image not found"}, status_code=404)

    img.similar_group_id = None
    log_action(db, "group_remove", image_id, f"从相似组 {group_id} 移除")
    db.commit()

    ref = request.headers.get("Referer", f"/groups/{group_id}")
    return RedirectResponse(url=ref, status_code=303)


@router.post("/groups/{group_id}/rename")
async def rename_group(request: Request, group_id: int, db: Session = Depends(get_db)):
    g = db.get(SimilarGroup, group_id)
    if not g:
        return JSONResponse({"error": "not found"}, status_code=404)
    form = await request.form()
    name = form.get("name", "").strip()
    if name:
        g.name = name
        log_action(db, "group_rename", group_id, f"重命名相似组: {name}")
        db.commit()
    ref = request.headers.get("Referer", "/groups")
    return RedirectResponse(url=ref, status_code=303)


@router.post("/groups/{group_id}/delete")
async def delete_group(request: Request, group_id: int, db: Session = Depends(get_db)):
    g = db.get(SimilarGroup, group_id)
    if not g:
        return JSONResponse({"error": "not found"}, status_code=404)
    db.execute(
        Image.__table__.update().where(Image.similar_group_id == group_id)
        .values(similar_group_id=None)
    )
    log_action(db, "group_delete", group_id, "删除相似组")
    db.delete(g)
    db.commit()
    ref = request.headers.get("Referer", "/groups")
    return RedirectResponse(url=ref, status_code=303)


@router.post("/groups/{group_id}/ungroup")
async def ungroup_images(request: Request, group_id: int, db: Session = Depends(get_db)):
    g = db.get(SimilarGroup, group_id)
    if not g:
        return JSONResponse({"error": "not found"}, status_code=404)
    db.execute(
        Image.__table__.update().where(Image.similar_group_id == group_id)
        .values(similar_group_id=None)
    )
    log_action(db, "group_ungroup", group_id, "取消分组")
    db.delete(g)
    db.commit()
    ref = request.headers.get("Referer", "/groups")
    return RedirectResponse(url=ref, status_code=303)
