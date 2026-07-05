import json
from collections import OrderedDict
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from pica.database import (
    Category, Image, ImageCategory, ImageStatus, ImageTag, Tag, log_action,
)
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
    "ai_status": Image.ai_status,
}


def _extract_all_tags(db: Session) -> list:
    """Extract all unique tags from the database."""
    all_tags = set()
    rows = db.execute(
        select(Image.suggested_tags).where(
            Image.suggested_tags.isnot(None), Image.suggested_tags != ""
        )
    ).scalars().all()
    for r in rows:
        try:
            tags = json.loads(r)
            if isinstance(tags, list):
                for t in tags:
                    if isinstance(t, str) and t.strip():
                        all_tags.add(t.strip())
        except (json.JSONDecodeError, TypeError):
            pass
    rows2 = db.execute(
        select(Image.confirmed_tags).where(
            Image.confirmed_tags.isnot(None), Image.confirmed_tags != ""
        )
    ).scalars().all()
    for r in rows2:
        try:
            tags = json.loads(r)
            if isinstance(tags, list):
                for t in tags:
                    if isinstance(t, str) and t.strip():
                        all_tags.add(t.strip())
        except (json.JSONDecodeError, TypeError):
            pass
    return sorted(all_tags)


@router.get("/pending/overview")
async def pending_overview(request: Request, db: Session = Depends(get_db)):
    """Return category/tag distribution for browse-first UI."""
    # Category breakdown (using confirmed_categories, fallback to suggested)
    cat_counts = []
    cats = db.query(Category).order_by(Category.sort_order, Category.name).all()
    for cat in cats:
        total = db.query(func.count(ImageCategory.id)).filter(
            ImageCategory.category_id == cat.id,
        ).join(Image, ImageCategory.image_id == Image.id).filter(
            Image.status == ImageStatus.PENDING
        ).scalar() or 0
        if total > 0:
            cat_counts.append({
                "id": cat.id,
                "name": cat.name,
                "color": cat.color,
                "total": total,
                "parent_id": cat.parent_id,
            })

    # Also collect categories from suggested_category JSON for images not yet linked
    from sqlalchemy import text
    rows = db.execute(text("""
        SELECT DISTINCT json_each.value as cat_name
        FROM images, json_each(images.suggested_category)
        WHERE images.status = 'pending' AND images.suggested_category IS NOT NULL
    """)).scalars().all()
    existing_names = {c["name"] for c in cat_counts}
    for name in rows:
        if name not in existing_names:
            cat_counts.append({
                "id": 0, "name": name, "color": "#8E8E93",
                "total": None, "parent_id": None,
            })

    # Tag breakdown
    tag_counts = []
    tags = db.query(Tag).order_by(Tag.name).all()
    for tag in tags:
        total = db.query(func.count(ImageTag.id)).filter(
            ImageTag.tag_id == tag.id,
        ).join(Image, ImageTag.image_id == Image.id).filter(
            Image.status == ImageStatus.PENDING
        ).scalar() or 0
        if total > 0:
            tag_counts.append({
                "id": tag.id, "name": tag.name,
                "color": tag.color, "total": total,
            })

    # Work name breakdown
    work_counts = []
    work_rows = db.execute(
        select(Image.work_name, func.count(Image.id))
        .where(Image.status == ImageStatus.PENDING, Image.work_name.isnot(None), Image.work_name != "")
        .group_by(Image.work_name)
        .order_by(func.count(Image.id).desc())
        .limit(20)
    ).all()
    for name, cnt in work_rows:
        work_counts.append({"name": name, "total": cnt})

    # Type breakdown
    type_counts = []
    type_rows = db.execute(
        select(Image.image_type, func.count(Image.id))
        .where(Image.status == ImageStatus.PENDING, Image.image_type.isnot(None), Image.image_type != "")
        .group_by(Image.image_type)
        .order_by(func.count(Image.id).desc())
    ).all()
    for name, cnt in type_rows:
        type_counts.append({"name": name, "total": cnt})

    # AI status breakdown
    ai_status_counts = []
    for st in ["pending", "processing", "done", "failed"]:
        cnt = db.query(func.count(Image.id)).filter(
            Image.status == ImageStatus.PENDING, Image.ai_status == st
        ).scalar() or 0
        if cnt > 0:
            ai_status_counts.append({"name": st, "total": cnt})

    total_pending = db.query(func.count(Image.id)).filter(
        Image.status == ImageStatus.PENDING
    ).scalar() or 0

    return JSONResponse({
        "total_pending": total_pending,
        "categories": cat_counts,
        "tags": tag_counts,
        "works": work_counts,
        "types": type_counts,
        "ai_statuses": ai_status_counts,
    })


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
    has_text = params.get("has_text", "")

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
    if has_text == "1":
        filters.append(Image.has_text == 1)

    sort_col = SORT_MAP.get(sort, Image.created_at)
    order_by = sort_col.desc() if order == "desc" else sort_col.asc()

    ctx = {
        "request": request,
        "categories": cfg.categories,
        "group_by": group_by,
        "view": view,
        "type_values": _get_type_values(db),
        "work_values": _get_work_values(db),
        "all_tags": _extract_all_tags(db),
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


@router.get("/pending/{image_id}", response_class=HTMLResponse)
async def pending_detail(request: Request, image_id: int, db: Session = Depends(get_db)):
    cfg = request.app.state.cfg
    img = db.get(Image, image_id)
    if not img:
        return HTMLResponse("Not found", status_code=404)
    similar = []
    if img.similar_group_id:
        similar = db.execute(
            select(Image).where(
                Image.similar_group_id == img.similar_group_id,
                Image.id != img.id,
            ).limit(12)
        ).scalars().all()
    return request.app.state.templates.TemplateResponse(
        "detail.html",
        {"request": request, "img": img, "categories": cfg.categories, "similar_images": similar},
    )


@router.get("/pending/{image_id}/data")
async def pending_image_data(image_id: int, db: Session = Depends(get_db)):
    img = db.get(Image, image_id)
    if not img:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {
        "id": img.id,
        "md5_hash": img.md5_hash,
        "filename": img.filename,
        "suggested_category": img.suggested_category_list,
        "suggested_tags": img.suggested_tags_list,
        "work_name": img.work_name or "",
        "image_type": img.image_type or "",
        "all_tags": sorted(set(
            img.suggested_tags_list + img.confirmed_tags_list
        )) if img.confirmed_tags_list else img.suggested_tags_list,
    }


@router.post("/pending/{image_id}/edit")
async def edit_pending_image(request: Request, image_id: int, db: Session = Depends(get_db)):
    img = db.get(Image, image_id)
    if not img or img.status != ImageStatus.PENDING:
        return JSONResponse({"error": "not found"}, status_code=404)
    form = await request.form()
    category = form.get("category", "")
    tags = form.get("tags", "")
    work = form.get("work", "")
    img_type = form.get("image_type", "")
    if category:
        cat_list = [c.strip() for c in category.split(",") if c.strip()]
        img.suggested_category = json.dumps(cat_list, ensure_ascii=False)
        db.query(ImageCategory).filter_by(image_id=img.id, source="suggested").delete()
        for name in cat_list:
            cat = db.query(Category).filter_by(name=name).first()
            if not cat:
                cat = Category(name=name)
                db.add(cat)
                db.flush()
            db.add(ImageCategory(image_id=img.id, category_id=cat.id, source="suggested"))
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        img.suggested_tags = json.dumps(tag_list, ensure_ascii=False)
        db.query(ImageTag).filter_by(image_id=img.id, source="suggested").delete()
        for name in tag_list:
            tag = db.query(Tag).filter_by(name=name).first()
            if not tag:
                tag = Tag(name=name)
                db.add(tag)
                db.flush()
            db.add(ImageTag(image_id=img.id, tag_id=tag.id, source="suggested"))
    if work:
        img.work_name = work
    if img_type:
        img.image_type = img_type
    img.user_edited = 1
    img.processed_at = datetime.utcnow()
    log_action(db, "edit", image_id, f"编辑: category={category}, tags={tags}, work={work}, type={img_type}")
    db.commit()
    ref = request.headers.get("Referer", "/pending")
    return RedirectResponse(url=ref, status_code=303)


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
    raw_work = form.get("work", "")
    raw_type = form.get("image_type", "")

    if raw_category:
        confirmed_category = [c.strip() for c in raw_category.split(",") if c.strip()]
    else:
        confirmed_category = img.suggested_category_list

    if raw_tags:
        confirmed_tags = [t.strip() for t in raw_tags.split(",") if t.strip()]
    else:
        confirmed_tags = img.suggested_tags_list

    if raw_work:
        img.work_name = raw_work.strip()
    if raw_type:
        img.image_type = raw_type.strip()

    primary_category = confirmed_category[0] if confirmed_category else "未分类"

    archive_dest = archive_image(img.pending_path, img.md5_hash, primary_category, cfg)
    if not archive_dest:
        return JSONResponse({"success": False, "error": "archive failed"}, status_code=500)

    img.confirmed_category = json.dumps(confirmed_category, ensure_ascii=False)
    img.confirmed_tags = json.dumps(confirmed_tags, ensure_ascii=False)
    img.archive_path = str(archive_dest)
    img.status = ImageStatus.CONFIRMED
    img.confirmed_at = datetime.utcnow()
    img.processed_at = datetime.utcnow()
    log_action(db, "confirm", img.id, f"归档: {primary_category}")

    # Write to new junction tables
    db.query(ImageCategory).filter_by(image_id=img.id, source="confirmed").delete()
    db.query(ImageTag).filter_by(image_id=img.id, source="confirmed").delete()
    for name in confirmed_category:
        cat = db.query(Category).filter_by(name=name).first()
        if not cat:
            cat = Category(name=name)
            db.add(cat)
            db.flush()
        db.add(ImageCategory(image_id=img.id, category_id=cat.id, source="confirmed"))
    for name in confirmed_tags:
        tag = db.query(Tag).filter_by(name=name).first()
        if not tag:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()
        db.add(ImageTag(image_id=img.id, tag_id=tag.id, source="confirmed"))

    db.commit()

    cleanup_pending(img.pending_path)

    ref = request.headers.get("Referer", "/pending")
    return RedirectResponse(url=ref, status_code=303)


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
        img.processed_at = datetime.utcnow()
        log_action(db, "confirm", img.id, f"批量归档: {category}")

        # Write to junction tables
        db.query(ImageCategory).filter_by(image_id=img.id, source="confirmed").delete()
        db.query(ImageTag).filter_by(image_id=img.id, source="confirmed").delete()
        for name in confirmed_cat:
            cat = db.query(Category).filter_by(name=name).first()
            if not cat:
                cat = Category(name=name)
                db.add(cat)
                db.flush()
            db.add(ImageCategory(image_id=img.id, category_id=cat.id, source="confirmed"))
        suggested_tags = img.suggested_tags_list
        for name in suggested_tags:
            tag = db.query(Tag).filter_by(name=name).first()
            if not tag:
                tag = Tag(name=name)
                db.add(tag)
                db.flush()
            db.add(ImageTag(image_id=img.id, tag_id=tag.id, source="confirmed"))

        cleanup_pending(img.pending_path)
        count += 1
    db.commit()

    return RedirectResponse(url=form.get("redirect", "/pending"), status_code=303)


@router.post("/pending/batch-edit")
async def batch_edit_pending(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    image_ids = form.getlist("image_ids")
    category = form.get("category", "").strip()
    tags_str = form.get("tags", "").strip()
    work = form.get("work", "").strip()
    img_type = form.get("image_type", "").strip()

    count = 0
    for img_id_str in image_ids:
        img = db.get(Image, int(img_id_str))
        if not img or img.status != ImageStatus.PENDING:
            continue
        if category:
            cat_list = [c.strip() for c in category.split(",") if c.strip()]
            img.suggested_category = json.dumps(cat_list, ensure_ascii=False)
            db.query(ImageCategory).filter_by(image_id=img.id, source="suggested").delete()
            for name in cat_list:
                cat = db.query(Category).filter_by(name=name).first()
                if not cat:
                    cat = Category(name=name)
                    db.add(cat)
                    db.flush()
                db.add(ImageCategory(image_id=img.id, category_id=cat.id, source="suggested"))
        if tags_str:
            tag_list = [t.strip() for t in tags_str.split(",") if t.strip()]
            img.suggested_tags = json.dumps(tag_list, ensure_ascii=False)
            db.query(ImageTag).filter_by(image_id=img.id, source="suggested").delete()
            for name in tag_list:
                tag = db.query(Tag).filter_by(name=name).first()
                if not tag:
                    tag = Tag(name=name)
                    db.add(tag)
                    db.flush()
                db.add(ImageTag(image_id=img.id, tag_id=tag.id, source="suggested"))
        if work:
            img.work_name = work
        if img_type:
            img.image_type = img_type
        img.user_edited = 1
        img.processed_at = datetime.utcnow()
        log_action(db, "batch_edit", img.id, f"批量编辑: category={category}, tags={tags_str}, work={work}, type={img_type}")
        count += 1
    db.commit()
    return JSONResponse({"success": True, "count": count})


@router.post("/pending/batch-reject")
async def batch_reject(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    image_ids = form.getlist("image_ids")
    for img_id in image_ids:
        img = db.get(Image, int(img_id))
        if not img or img.status != ImageStatus.PENDING:
            continue
        img.status = ImageStatus.RECYCLED
        img.processed_at = datetime.utcnow()
        log_action(db, "recycle", img.id, "批量移入回收站")
        cleanup_pending(img.pending_path)
    db.commit()
    return RedirectResponse(url=form.get("redirect", "/pending"), status_code=303)


@router.post("/pending/{image_id}/reject")
async def reject_image(image_id: int, db: Session = Depends(get_db)):
    img = db.get(Image, image_id)
    if not img:
        return JSONResponse({"success": False, "error": "not found"}, status_code=404)

    img.status = ImageStatus.RECYCLED
    img.processed_at = datetime.utcnow()
    log_action(db, "recycle", image_id, "移入回收站")
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
