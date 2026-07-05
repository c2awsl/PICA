import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from pica.database import Image, ImageTag, ImageStatus, Tag

router = APIRouter()


def get_db(request: Request) -> Session:
    engine = request.app.state.engine
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()


def _collect_tags(db: Session) -> list[dict]:
    """Get all tags with image counts from the unified Tag table."""
    tags = db.query(Tag).order_by(Tag.name).all()
    result = []
    for t in tags:
        total = db.query(func.count(ImageTag.id)).filter(ImageTag.tag_id == t.id).scalar() or 0
        pending = db.query(func.count(ImageTag.id)).filter(
            ImageTag.tag_id == t.id,
            Image.status == ImageStatus.PENDING,
        ).join(Image, ImageTag.image_id == Image.id).scalar() or 0
        confirmed = db.query(func.count(ImageTag.id)).filter(
            ImageTag.tag_id == t.id,
            Image.status == ImageStatus.CONFIRMED,
        ).join(Image, ImageTag.image_id == Image.id).scalar() or 0
        result.append({
            "id": t.id,
            "name": t.name,
            "color": t.color,
            "total": total,
            "pending": pending,
            "confirmed": confirmed,
        })
    return sorted(result, key=lambda x: x["total"], reverse=True)


@router.get("/tags", response_class=HTMLResponse)
async def tags_page(request: Request, db: Session = Depends(get_db)):
    tags = _collect_tags(db)
    return request.app.state.templates.TemplateResponse(
        "tags.html",
        {"request": request, "tags": tags},
    )


@router.get("/tags/data")
async def tags_data(request: Request, db: Session = Depends(get_db)):
    return JSONResponse({"tags": _collect_tags(db)})


@router.post("/tags/create")
async def create_tag(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    name = form.get("name", "").strip()
    color = form.get("color", "#8E8E93").strip()
    if not name:
        return JSONResponse({"success": False, "error": "name required"})
    existing = db.query(Tag).filter_by(name=name).first()
    if existing:
        return JSONResponse({"success": False, "error": "tag already exists"})
    tag = Tag(name=name, color=color)
    db.add(tag)
    db.commit()
    return JSONResponse({"success": True, "id": tag.id})


@router.post("/tags/merge")
async def merge_tags(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    source = form.get("source", "").strip()
    target = form.get("target", "").strip()
    if not source or not target or source == target:
        return JSONResponse({"success": False, "error": "invalid names"})

    source_tag = db.query(Tag).filter_by(name=source).first()
    target_tag = db.query(Tag).filter_by(name=target).first()
    if not source_tag or not target_tag:
        return JSONResponse({"success": False, "error": "tag not found"})

    # Reassign all ImageTag links from source to target
    links = db.query(ImageTag).filter_by(tag_id=source_tag.id).all()
    for link in links:
        existing = db.query(ImageTag).filter_by(
            image_id=link.image_id, tag_id=target_tag.id, source=link.source
        ).first()
        if not existing:
            link.tag_id = target_tag.id
        else:
            db.delete(link)

    # Delete source tag
    db.query(Tag).filter_by(id=source_tag.id).delete()

    # Also update old JSON fields for backward compat
    for img, in db.query(Image).all():
        for col, prop in [(Image.suggested_tags, "suggested_tags_list"),
                          (Image.confirmed_tags, "confirmed_tags_list")]:
            lst = getattr(img, prop)
            mod = False
            if source in lst:
                lst.remove(source)
                if target not in lst:
                    lst.append(target)
                mod = True
            if mod:
                setattr(img, col, json.dumps(lst, ensure_ascii=False))

    db.commit()
    return JSONResponse({"success": True})


@router.post("/tags/rename")
async def rename_tag(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    old_name = form.get("old_name", "").strip()
    new_name = form.get("new_name", "").strip()
    if not old_name or not new_name or old_name == new_name:
        return JSONResponse({"success": False, "error": "invalid names"})

    tag = db.query(Tag).filter_by(name=old_name).first()
    if not tag:
        return JSONResponse({"success": False, "error": "tag not found"})

    tag.name = new_name

    # Also update old JSON fields
    for img, in db.query(Image).all():
        for col, prop in [(Image.suggested_tags, "suggested_tags_list"),
                          (Image.confirmed_tags, "confirmed_tags_list")]:
            lst = getattr(img, prop)
            if old_name in lst:
                idx = lst.index(old_name)
                lst[idx] = new_name
                setattr(img, col, json.dumps(lst, ensure_ascii=False))

    db.commit()
    return JSONResponse({"success": True})


@router.post("/tags/delete")
async def delete_tag(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    tag_name = form.get("tag", "").strip()
    if not tag_name:
        return JSONResponse({"success": False, "error": "invalid name"})

    tag = db.query(Tag).filter_by(name=tag_name).first()
    if not tag:
        return JSONResponse({"success": False, "error": "tag not found"})

    # Remove links
    db.query(ImageTag).filter_by(tag_id=tag.id).delete()
    db.delete(tag)

    # Also update old JSON fields
    for img, in db.query(Image).all():
        for col, prop in [(Image.suggested_tags, "suggested_tags_list"),
                          (Image.confirmed_tags, "confirmed_tags_list")]:
            lst = getattr(img, prop)
            if tag_name in lst:
                lst.remove(tag_name)
                setattr(img, col, json.dumps(lst, ensure_ascii=False))

    db.commit()
    return JSONResponse({"success": True})
