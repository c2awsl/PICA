from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from pica.database import Image, ImageStatus, SimilarGroup

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
    groups = db.execute(
        select(SimilarGroup).order_by(SimilarGroup.created_at.desc())
    ).scalars().all()

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
        {"request": request, "group_data": group_data},
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


@router.post("/groups/{group_id}/rename")
async def rename_group(request: Request, group_id: int, db: Session = Depends(get_db)):
    g = db.get(SimilarGroup, group_id)
    if not g:
        return JSONResponse({"error": "not found"}, status_code=404)
    form = await request.form()
    name = form.get("name", "").strip()
    if name:
        g.name = name
        db.commit()
    ref = request.headers.get("Referer", "/groups")
    return RedirectResponse(url=ref, status_code=303)


@router.post("/groups/{group_id}/delete")
async def delete_group(request: Request, group_id: int, db: Session = Depends(get_db)):
    g = db.get(SimilarGroup, group_id)
    if not g:
        return JSONResponse({"error": "not found"}, status_code=404)
    # Unlink all images
    db.execute(
        Image.__table__.update().where(Image.similar_group_id == group_id)
        .values(similar_group_id=None)
    )
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
    db.delete(g)
    db.commit()
    ref = request.headers.get("Referer", "/groups")
    return RedirectResponse(url=ref, status_code=303)
