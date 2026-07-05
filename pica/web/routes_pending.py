import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from pica.database import Image, ImageStatus, get_session
from pica.archiver import archive_image, cleanup_pending

router = APIRouter()


def get_db(request: Request) -> Session:
    engine = request.app.state.engine
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()


@router.get("/", response_class=HTMLResponse)
@router.get("/pending", response_class=HTMLResponse)
async def pending_list(request: Request, db: Session = Depends(get_db)):
    cfg = request.app.state.cfg
    group_by = request.query_params.get("group", "none")

    if group_by == "sim":
        sub = (
            select(Image.similar_group_id, func.count(Image.id).label("cnt"))
            .where(Image.status == ImageStatus.PENDING)
            .group_by(Image.similar_group_id)
            .subquery()
        )
        stmt = (
            select(Image)
            .where(Image.status == ImageStatus.PENDING)
            .order_by(Image.similar_group_id, Image.created_at.desc())
            .limit(200)
        )
        images = db.execute(stmt).scalars().all()

        from collections import OrderedDict
        groups = OrderedDict()
        for img in images:
            gid = img.similar_group_id or 0
            if gid not in groups:
                groups[gid] = []
            groups[gid].append(img)

        return request.app.state.templates.TemplateResponse(
            "pending.html",
            {
                "request": request,
                "images": images,
                "groups": groups,
                "categories": cfg.categories,
                "group_by": "sim",
            },
        )

    stmt = (
        select(Image)
        .where(Image.status == ImageStatus.PENDING)
        .order_by(Image.created_at.desc())
        .limit(100)
    )
    images = db.execute(stmt).scalars().all()
    return request.app.state.templates.TemplateResponse(
        "pending.html",
        {"request": request, "images": images, "categories": cfg.categories, "group_by": "none"},
    )


@router.get("/pending/{image_id}", response_class=HTMLResponse)
async def pending_detail(request: Request, image_id: int, db: Session = Depends(get_db)):
    cfg = request.app.state.cfg
    img = db.get(Image, image_id)
    if not img:
        return HTMLResponse("Not found", status_code=404)
    return request.app.state.templates.TemplateResponse(
        "detail.html",
        {"request": request, "img": img, "categories": cfg.categories},
    )


@router.post("/pending/{image_id}/confirm")
async def confirm_image(
    request: Request,
    image_id: int,
    db: Session = Depends(get_db),
):
    cfg = request.app.state.cfg
    img = db.get(Image, image_id)
    if not img:
        return JSONResponse({"success": False, "error": "not found"}, status_code=404)

    form = await request.form()
    raw_category = form.get("category", "")
    raw_tags = form.get("tags", "")

    if raw_category:
        confirmed_category = [c.strip() for c in raw_category.split(",") if c.strip()]
    else:
        confirmed_category = img.suggested_category_list

    if raw_tags:
        confirmed_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    else:
        confirmed_tags = img.suggested_tags_list

    primary_category = confirmed_category[0] if confirmed_category else "未分类"

    archive_dest = archive_image(img.pending_path, img.md5_hash, primary_category, cfg)
    if not archive_dest:
        return JSONResponse({"success": False, "error": "archive failed"}, status_code=500)

    img.confirmed_category = json.dumps(confirmed_category, ensure_ascii=False)
    img.confirmed_tags = json.dumps(confirmed_tags, ensure_ascii=False)
    img.archive_path = str(archive_dest)
    img.status = ImageStatus.CONFIRMED
    img.confirmed_at = datetime.utcnow()
    db.commit()

    cleanup_pending(img.pending_path)

    return RedirectResponse(url="/pending", status_code=303)


@router.post("/pending/batch-confirm")
async def batch_confirm(request: Request, db: Session = Depends(get_db)):
    cfg = request.app.state.cfg
    form = await request.form()
    image_ids = form.getlist("image_ids")
    raw_category = form.get("category", "")
    category = raw_category.strip() or "未分类"

    count = 0
    for img_id in image_ids:
        img = db.get(Image, int(img_id))
        if not img or img.status != ImageStatus.PENDING:
            continue
        archive_dest = archive_image(img.pending_path, img.md5_hash, category, cfg)
        if not archive_dest:
            continue
        confirmed_cat = [category]
        if img.suggested_category_list:
            for c in img.suggested_category_list:
                if c not in confirmed_cat:
                    confirmed_cat.append(c)
        img.confirmed_category = json.dumps(confirmed_cat, ensure_ascii=False)
        img.confirmed_tags = img.suggested_tags
        img.archive_path = str(archive_dest)
        img.status = ImageStatus.CONFIRMED
        img.confirmed_at = datetime.utcnow()
        cleanup_pending(img.pending_path)
        count += 1
    db.commit()

    return RedirectResponse(url=form.get("redirect", "/pending"), status_code=303)


@router.post("/pending/{image_id}/reject")
async def reject_image(image_id: int, db: Session = Depends(get_db)):
    img = db.get(Image, image_id)
    if not img:
        return JSONResponse({"success": False, "error": "not found"}, status_code=404)

    img.status = ImageStatus.REJECTED
    db.commit()

    cleanup_pending(img.pending_path)

    return RedirectResponse(url="/pending", status_code=303)
