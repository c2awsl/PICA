import json
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from pica.database import Image, ImageStatus
from pica.archiver import archive_image, cleanup_pending

router = APIRouter()


def get_db(request: Request) -> Session:
    engine = request.app.state.engine
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()


SORT_MAP = {
    "filename": Image.filename,
    "file_size": Image.file_size,
    "created_at": Image.created_at,
    "confirmed_at": Image.confirmed_at,
    "image_type": Image.image_type,
    "work_name": Image.work_name,
    "suggested_category": Image.suggested_category,
    "width": Image.width,
    "height": Image.height,
}


@router.get("/", response_class=HTMLResponse)
@router.get("/pending", response_class=HTMLResponse)
async def pending_list(request: Request, db: Session = Depends(get_db)):
    cfg = request.app.state.cfg
    params = request.query_params

    view = params.get("view", "lg-icons")
    group_by = params.get("group", "none")
    work = params.get("work", "")
    img_type = params.get("type", "")
    category = params.get("category", "")
    q = params.get("q", "")
    sort = params.get("sort", "created_at")
    order = params.get("order", "desc")
    ai_status_filter = params.get("ai_status", "")

    filters = [Image.status == ImageStatus.PENDING]
    if work:
        filters.append(Image.work_name == work)
    if img_type:
        filters.append(Image.image_type == img_type)
    if category:
        filters.append(Image.suggested_category.like(f"%{category}%"))
    if q:
        filters.append(Image.filename.ilike(f"%{q}%"))
    if ai_status_filter:
        filters.append(Image.ai_status == ai_status_filter)

    sort_col = SORT_MAP.get(sort, Image.created_at)
    order_by = sort_col.desc() if order == "desc" else sort_col.asc()

    ctx = {
        "request": request,
        "categories": cfg.categories,
        "group_by": group_by,
        "view": view,
        "type_values": _get_type_values(db),
        "work_values": _get_work_values(db),
        "sort": sort,
        "order": order,
    }

    if group_by == "sim":
        stmt = (
            select(Image)
            .where(*filters)
            .order_by(Image.similar_group_id, order_by)
            .limit(400)
        )
        images = db.execute(stmt).scalars().all()

        from collections import OrderedDict
        groups = OrderedDict()
        for img in images:
            gid = img.similar_group_id or 0
            if gid not in groups:
                groups[gid] = []
            groups[gid].append(img)

        ctx["images"] = images
        ctx["groups"] = groups
        return request.app.state.templates.TemplateResponse("pending.html", ctx)

    stmt = (
        select(Image)
        .where(*filters)
        .order_by(order_by)
        .limit(400)
    )
    images = db.execute(stmt).scalars().all()
    ctx["images"] = images
    return request.app.state.templates.TemplateResponse("pending.html", ctx)


def _get_type_values(db: Session) -> list:
    rows = db.execute(
        select(Image.image_type)
        .where(Image.image_type.isnot(None), Image.image_type != "")
        .distinct()
        .order_by(Image.image_type)
    ).scalars().all()
    return rows


def _get_work_values(db: Session) -> list:
    rows = db.execute(
        select(Image.work_name)
        .where(Image.work_name.isnot(None), Image.work_name != "")
        .distinct()
        .order_by(Image.work_name)
    ).scalars().all()
    return rows


def _get_type_values(db: Session) -> list:
    rows = db.execute(
        select(Image.image_type)
        .where(Image.image_type.isnot(None), Image.image_type != "")
        .distinct()
        .order_by(Image.image_type)
    ).scalars().all()
    return rows


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


@router.post("/pending/batch-reject")
async def batch_reject(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    image_ids = form.getlist("image_ids")
    for img_id in image_ids:
        img = db.get(Image, int(img_id))
        if not img or img.status != ImageStatus.PENDING:
            continue
        img.status = ImageStatus.REJECTED
        cleanup_pending(img.pending_path)
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


@router.post("/pending/{image_id}/retry-ai")
async def retry_ai(request: Request, image_id: int, db: Session = Depends(get_db)):
    img = db.get(Image, image_id)
    if not img:
        return JSONResponse({"success": False, "error": "not found"}, status_code=404)
    img.ai_status = "pending"
    db.commit()
    ref = request.headers.get("Referer", "/pending")
    return RedirectResponse(url=ref, status_code=303)


@router.post("/pending/batch-retry-ai")
async def batch_retry_ai(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    image_ids = form.getlist("image_ids")
    for img_id in image_ids:
        img = db.get(Image, int(img_id))
        if not img:
            continue
        img.ai_status = "pending"
    db.commit()
    return RedirectResponse(url=form.get("redirect", "/pending"), status_code=303)
