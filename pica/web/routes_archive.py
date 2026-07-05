import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from pica.database import Image, ImageStatus

router = APIRouter()


def get_db(request: Request) -> Session:
    engine = request.app.state.engine
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()


@router.get("/archive", response_class=HTMLResponse)
async def archive_list(
    request: Request,
    category: str = Query(None),
    tag: str = Query(None),
    q: str = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    cfg = request.app.state.cfg

    base = select(Image).where(Image.status == ImageStatus.CONFIRMED)
    if category:
        base = base.where(Image.confirmed_category.like(f"%{category}%"))
    if tag:
        base = base.where(Image.confirmed_tags.like(f"%{tag}%"))
    if q:
        base = base.where(
            Image.filename.ilike(f"%{q}%")
            | Image.confirmed_category.ilike(f"%{q}%")
            | Image.confirmed_tags.ilike(f"%{q}%")
            | Image.work_name.ilike(f"%{q}%")
            | Image.extracted_text.ilike(f"%{q}%")
        )

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar() or 0

    stmt = base.order_by(Image.confirmed_at.desc()).offset((page - 1) * per_page).limit(per_page)
    images = db.execute(stmt).scalars().all()

    # Collect category counts for filter UI
    cat_counts = {}
    for cat in cfg.categories:
        cnt = db.execute(
            select(func.count(Image.id))
            .where(
                Image.status == ImageStatus.CONFIRMED,
                Image.confirmed_category.like(f"%{cat}%"),
            )
        ).scalar() or 0
        if cnt:
            cat_counts[cat] = cnt

    return request.app.state.templates.TemplateResponse(
        "archive.html",
        {
            "request": request,
            "images": images,
            "categories": cfg.categories,
            "category_counts": cat_counts,
            "current_category": category or "",
            "current_tag": tag or "",
            "q": q or "",
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        },
    )


@router.get("/archive/{image_id}", response_class=HTMLResponse)
async def archive_detail(request: Request, image_id: int, db: Session = Depends(get_db)):
    cfg = request.app.state.cfg
    img = db.get(Image, image_id)
    if not img or img.status != ImageStatus.CONFIRMED:
        return HTMLResponse("Not found", status_code=404)
    similar = []
    if img.similar_group_id:
        similar = db.execute(
            select(Image).where(
                Image.similar_group_id == img.similar_group_id,
                Image.id != img.id,
            ).limit(12)
        ).scalars().all()
    prev_img = db.execute(
        select(Image).where(
            Image.status == ImageStatus.CONFIRMED,
            Image.confirmed_at > img.confirmed_at,
        ).order_by(Image.confirmed_at.asc()).limit(1)
    ).scalar_one_or_none()
    next_img = db.execute(
        select(Image).where(
            Image.status == ImageStatus.CONFIRMED,
            Image.confirmed_at < img.confirmed_at,
        ).order_by(Image.confirmed_at.desc()).limit(1)
    ).scalar_one_or_none()
    return request.app.state.templates.TemplateResponse(
        "detail.html",
        {
            "request": request,
            "img": img,
            "categories": cfg.categories,
            "similar_images": similar,
            "prev_id": prev_img.id if prev_img else None,
            "next_id": next_img.id if next_img else None,
        },
    )


@router.post("/archive/{image_id}/edit")
async def edit_archive_image(request: Request, image_id: int, db: Session = Depends(get_db)):
    img = db.get(Image, image_id)
    if not img or img.status != ImageStatus.CONFIRMED:
        return JSONResponse({"error": "not found"}, status_code=404)
    form = await request.form()
    category = form.get("category", "")
    tags = form.get("tags", "")
    work = form.get("work", "")
    img_type = form.get("image_type", "")
    if category:
        img.confirmed_category = json.dumps(
            [c.strip() for c in category.split(",") if c.strip()],
            ensure_ascii=False,
        )
    if tags:
        img.confirmed_tags = json.dumps(
            [t.strip() for t in tags.split(",") if t.strip()],
            ensure_ascii=False,
        )
    if work:
        img.work_name = work.strip()
    if img_type:
        img.image_type = img_type.strip()
    db.commit()
    ref = request.headers.get("Referer", f"/archive/{image_id}")
    return RedirectResponse(url=ref, status_code=303)


@router.post("/archive/batch-edit")
async def batch_edit_archive(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    image_ids = form.getlist("image_ids")
    action = form.get("action", "")
    value = form.get("value", "")

    count = 0
    for img_id in image_ids:
        img = db.get(Image, int(img_id))
        if not img or img.status != ImageStatus.CONFIRMED:
            continue
        if action == "add_tag" and value:
            tags = img.confirmed_tags_list
            if value.strip() not in tags:
                tags.append(value.strip())
                img.confirmed_tags = json.dumps(tags, ensure_ascii=False)
        elif action == "remove_tag" and value:
            tags = img.confirmed_tags_list
            if value.strip() in tags:
                tags.remove(value.strip())
                img.confirmed_tags = json.dumps(tags, ensure_ascii=False)
        elif action == "set_category" and value:
            img.confirmed_category = json.dumps(
                [c.strip() for c in value.split(",") if c.strip()],
                ensure_ascii=False,
            )
        elif action == "set_work" and value:
            img.work_name = value.strip()
        count += 1
    db.commit()
    return JSONResponse({"success": True, "count": count})
