from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
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


@router.get("/stats", response_class=HTMLResponse)
async def stats(request: Request, db: Session = Depends(get_db)):
    cfg = request.app.state.cfg

    total = db.execute(select(func.count(Image.id))).scalar() or 0
    pending_count = db.execute(
        select(func.count(Image.id)).where(Image.status == ImageStatus.PENDING)
    ).scalar() or 0
    confirmed_count = db.execute(
        select(func.count(Image.id)).where(Image.status == ImageStatus.CONFIRMED)
    ).scalar() or 0
    rejected_count = db.execute(
        select(func.count(Image.id)).where(Image.status == ImageStatus.REJECTED)
    ).scalar() or 0

    category_counts = {}
    for cat in cfg.categories:
        count = db.execute(
            select(func.count(Image.id))
            .where(
                Image.status == ImageStatus.CONFIRMED,
                Image.confirmed_category.like(f"%{cat}%"),
            )
        ).scalar() or 0
        category_counts[cat] = count

    return request.app.state.templates.TemplateResponse(
        "stats.html",
        {
            "request": request,
            "total": total,
            "pending_count": pending_count,
            "confirmed_count": confirmed_count,
            "rejected_count": rejected_count,
            "category_counts": category_counts,
        },
    )
