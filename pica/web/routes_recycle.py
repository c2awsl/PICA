from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from pica.database import AuditLog, Image, ImageStatus, log_action

router = APIRouter()


def get_db(request: Request) -> Session:
    engine = request.app.state.engine
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()


@router.get("/recycle", response_class=HTMLResponse)
async def recycle_page(request: Request, db: Session = Depends(get_db)):
    images = db.execute(
        select(Image)
        .where(Image.status == ImageStatus.RECYCLED)
        .order_by(Image.confirmed_at.desc())
        .limit(200)
    ).scalars().all()
    return request.app.state.templates.TemplateResponse(
        "recycle.html",
        {"request": request, "images": images},
    )


@router.post("/recycle/{image_id}/restore")
async def restore_image(image_id: int, db: Session = Depends(get_db)):
    img = db.get(Image, image_id)
    if not img or img.status != ImageStatus.RECYCLED:
        return JSONResponse({"error": "not found"}, status_code=404)
    img.status = ImageStatus.PENDING
    img.processed_at = datetime.utcnow()
    log_action(db, "restore", image_id, "从回收站恢复")
    db.commit()
    return RedirectResponse(url="/recycle", status_code=303)


@router.post("/recycle/{image_id}/delete-permanent")
async def permanent_delete(image_id: int, db: Session = Depends(get_db)):
    img = db.get(Image, image_id)
    if not img or img.status != ImageStatus.RECYCLED:
        return JSONResponse({"error": "not found"}, status_code=404)
    log_action(db, "permanent_delete", image_id, "永久删除")
    db.delete(img)
    db.commit()
    return RedirectResponse(url="/recycle", status_code=303)


@router.post("/recycle/batch-restore")
async def batch_restore(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    ids = form.getlist("image_ids")
    for sid in ids:
        img = db.get(Image, int(sid))
        if img and img.status == ImageStatus.RECYCLED:
            img.status = ImageStatus.PENDING
            img.processed_at = datetime.utcnow()
            log_action(db, "restore", img.id, "批量恢复")
    db.commit()
    return RedirectResponse(url="/recycle", status_code=303)


@router.post("/recycle/empty")
async def empty_recycle(db: Session = Depends(get_db)):
    images = db.execute(
        select(Image).where(Image.status == ImageStatus.RECYCLED)
    ).scalars().all()
    for img in images:
        log_action(db, "permanent_delete", img.id, "清空回收站")
        db.delete(img)
    db.commit()
    return RedirectResponse(url="/recycle", status_code=303)
