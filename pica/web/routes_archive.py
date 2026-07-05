from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
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

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar() or 0

    stmt = base.order_by(Image.confirmed_at.desc()).offset((page - 1) * per_page).limit(per_page)
    images = db.execute(stmt).scalars().all()

    return request.app.state.templates.TemplateResponse(
        "archive.html",
        {
            "request": request,
            "images": images,
            "categories": cfg.categories,
            "current_category": category or "",
            "current_tag": tag or "",
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        },
    )


@router.get("/archive/{image_id}", response_class=HTMLResponse)
async def archive_detail(request: Request, image_id: int, db: Session = Depends(get_db)):
    img = db.get(Image, image_id)
    if not img or img.status != ImageStatus.CONFIRMED:
        return HTMLResponse("Not found", status_code=404)
    return request.app.state.templates.TemplateResponse(
        "detail.html",
        {"request": request, "img": img, "readonly": True},
    )
