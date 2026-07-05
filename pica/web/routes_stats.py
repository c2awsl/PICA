from datetime import datetime, timedelta

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

    # AI stats
    ai_pending = db.execute(
        select(func.count(Image.id)).where(Image.ai_status == "pending")
    ).scalar() or 0
    ai_processing = db.execute(
        select(func.count(Image.id)).where(Image.ai_status == "processing")
    ).scalar() or 0
    ai_done = db.execute(
        select(func.count(Image.id)).where(Image.ai_status == "done")
    ).scalar() or 0
    ai_failed = db.execute(
        select(func.count(Image.id)).where(Image.ai_status == "failed")
    ).scalar() or 0

    # Active models
    ai_models = db.execute(
        select(Image.ai_model)
        .where(Image.ai_model.isnot(None))
        .distinct()
    ).scalars().all()

    # Recent activity (last 7 days)
    week_ago = datetime.utcnow() - timedelta(days=7)
    recent_confirmed = db.execute(
        select(func.count(Image.id)).where(
            Image.status == ImageStatus.CONFIRMED,
            Image.confirmed_at >= week_ago,
        )
    ).scalar() or 0
    recent_scanned = db.execute(
        select(func.count(Image.id)).where(
            Image.created_at >= week_ago,
        )
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

    # Work counts (top 10)
    work_counts_rows = db.execute(
        select(Image.work_name, func.count(Image.id).label("cnt"))
        .where(
            Image.status == ImageStatus.CONFIRMED,
            Image.work_name.isnot(None),
            Image.work_name != "",
        )
        .group_by(Image.work_name)
        .order_by(func.count(Image.id).desc())
        .limit(10)
    ).all()
    work_counts = {row.work_name: row.cnt for row in work_counts_rows}

    return request.app.state.templates.TemplateResponse(
        "stats.html",
        {
            "request": request,
            "total": total,
            "pending_count": pending_count,
            "confirmed_count": confirmed_count,
            "rejected_count": rejected_count,
            "ai_pending": ai_pending,
            "ai_processing": ai_processing,
            "ai_done": ai_done,
            "ai_failed": ai_failed,
            "ai_models": ai_models,
            "recent_confirmed": recent_confirmed,
            "recent_scanned": recent_scanned,
            "category_counts": category_counts,
            "work_counts": work_counts,
        },
    )
