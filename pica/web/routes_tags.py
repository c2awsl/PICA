import json
from collections import Counter

from fastapi import APIRouter, Depends, Request
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


def _collect_tags(db: Session) -> dict:
    """Extract all tags with usage counts from the DB."""
    counter = Counter()
    for col in [Image.suggested_tags, Image.confirmed_tags]:
        rows = db.execute(
            select(col).where(col.isnot(None), col != "")
        ).scalars().all()
        for r in rows:
            try:
                tags = json.loads(r)
                if isinstance(tags, list):
                    for t in tags:
                        if isinstance(t, str) and t.strip():
                            counter[t.strip()] += 1
            except (json.JSONDecodeError, TypeError):
                pass
    return dict(counter.most_common())


@router.get("/tags", response_class=HTMLResponse)
async def tags_page(request: Request, db: Session = Depends(get_db)):
    tags = _collect_tags(db)
    return request.app.state.templates.TemplateResponse(
        "tags.html",
        {"request": request, "tags": tags},
    )


@router.post("/tags/merge")
async def merge_tags(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    source = form.get("source", "").strip()
    target = form.get("target", "").strip()
    if not source or not target or source == target:
        return JSONResponse({"success": False, "error": "invalid names"})

    # Replace source with target in all suggested_tags columns
    for col, list_prop in [(Image.suggested_tags, "suggested_tags_list"),
                            (Image.confirmed_tags, "confirmed_tags_list")]:
        rows = db.execute(select(Image).where(col.like(f"%{source}%"))).scalars().all()
        for img in rows:
            tag_list = getattr(img, list_prop)
            if source in tag_list:
                tag_list.remove(source)
                if target not in tag_list:
                    tag_list.append(target)
                setattr(img, col, json.dumps(tag_list, ensure_ascii=False))
    db.commit()
    ref = request.headers.get("Referer", "/tags")
    return RedirectResponse(url=ref, status_code=303)


@router.post("/tags/rename")
async def rename_tag(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    old_name = form.get("old_name", "").strip()
    new_name = form.get("new_name", "").strip()
    if not old_name or not new_name or old_name == new_name:
        return JSONResponse({"success": False, "error": "invalid names"})

    for col, list_prop in [(Image.suggested_tags, "suggested_tags_list"),
                            (Image.confirmed_tags, "confirmed_tags_list")]:
        rows = db.execute(select(Image).where(col.like(f"%{old_name}%"))).scalars().all()
        for img in rows:
            tag_list = getattr(img, list_prop)
            if old_name in tag_list:
                idx = tag_list.index(old_name)
                tag_list[idx] = new_name
                setattr(img, col, json.dumps(tag_list, ensure_ascii=False))
    db.commit()
    ref = request.headers.get("Referer", "/tags")
    return RedirectResponse(url=ref, status_code=303)


@router.post("/tags/delete")
async def delete_tag(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    tag = form.get("tag", "").strip()
    if not tag:
        return JSONResponse({"success": False, "error": "invalid name"})

    for col, list_prop in [(Image.suggested_tags, "suggested_tags_list"),
                            (Image.confirmed_tags, "confirmed_tags_list")]:
        rows = db.execute(select(Image).where(col.like(f"%{tag}%"))).scalars().all()
        for img in rows:
            tag_list = getattr(img, list_prop)
            if tag in tag_list:
                tag_list.remove(tag)
                setattr(img, col, json.dumps(tag_list, ensure_ascii=False))
    db.commit()
    ref = request.headers.get("Referer", "/tags")
    return RedirectResponse(url=ref, status_code=303)
