from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from pica.database import AuditLog, Image, ImageStatus, SimilarGroup, StorageBox, StorageBoxItem, log_action

router = APIRouter()


def get_db(request: Request) -> Session:
    engine = request.app.state.engine
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()


@router.get("/boxes", response_class=HTMLResponse)
async def boxes_page(request: Request, db: Session = Depends(get_db)):
    boxes = db.execute(
        select(StorageBox).order_by(StorageBox.sort_order, StorageBox.created_at.desc())
    ).scalars().all()
    box_data = []
    for b in boxes:
        count = db.query(func.count(StorageBoxItem.id)).filter(
            StorageBoxItem.box_id == b.id
        ).scalar() or 0
        box_data.append({"box": b, "count": count})
    return request.app.state.templates.TemplateResponse(
        "boxes.html",
        {"request": request, "box_data": box_data},
    )


@router.get("/boxes/{box_id}", response_class=HTMLResponse)
async def box_detail(request: Request, box_id: int, db: Session = Depends(get_db)):
    box = db.get(StorageBox, box_id)
    if not box:
        return HTMLResponse("Not found", status_code=404)
    items = db.execute(
        select(StorageBoxItem).where(StorageBoxItem.box_id == box_id)
        .order_by(StorageBoxItem.created_at.desc())
    ).scalars().all()
    images = [it.image for it in items if it.image]
    return request.app.state.templates.TemplateResponse(
        "box_detail.html",
        {"request": request, "box": box, "images": images},
    )


@router.get("/boxes/data")
async def boxes_data(db: Session = Depends(get_db)):
    boxes = db.execute(
        select(StorageBox).order_by(StorageBox.sort_order, StorageBox.created_at.desc())
    ).scalars().all()
    result = []
    for b in boxes:
        count = db.query(func.count(StorageBoxItem.id)).filter(
            StorageBoxItem.box_id == b.id
        ).scalar() or 0
        result.append({
            "id": b.id, "name": b.name, "color": b.color,
            "count": count, "sort_order": b.sort_order,
        })
    return JSONResponse({"boxes": result})


@router.post("/boxes/create")
async def create_box(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    name = form.get("name", "").strip()
    color = form.get("color", "#007AFF").strip()
    if not name:
        return JSONResponse({"success": False, "error": "name required"})
    box = StorageBox(name=name, color=color)
    db.add(box)
    log_action(db, "create_box", details=f"创建储物箱: {name}")
    db.commit()
    return JSONResponse({"success": True, "id": box.id})


@router.post("/boxes/rename")
async def rename_box(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    box_id = int(form.get("id", "0"))
    name = form.get("name", "").strip()
    if not box_id or not name:
        return JSONResponse({"success": False, "error": "invalid params"})
    box = db.get(StorageBox, box_id)
    if not box:
        return JSONResponse({"success": False, "error": "not found"})
    old_name = box.name
    box.name = name
    log_action(db, "rename_box", details=f"储物箱重命名: {old_name} → {name}")
    db.commit()
    return JSONResponse({"success": True})


@router.post("/boxes/delete")
async def delete_box(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    box_id = int(form.get("id", "0"))
    if not box_id:
        return JSONResponse({"success": False, "error": "invalid id"})
    box = db.get(StorageBox, box_id)
    if not box:
        return JSONResponse({"success": False, "error": "not found"})
    log_action(db, "delete_box", details=f"删除储物箱: {box.name}")
    db.delete(box)
    db.commit()
    return JSONResponse({"success": True})


@router.post("/boxes/{box_id}/add-image")
async def add_image_to_box(request: Request, box_id: int, db: Session = Depends(get_db)):
    box = db.get(StorageBox, box_id)
    if not box:
        return JSONResponse({"error": "box not found"}, status_code=404)
    form = await request.form()
    image_id = int(form.get("image_id", "0"))
    if not image_id:
        return JSONResponse({"error": "invalid image_id"}, status_code=400)
    existing = db.query(StorageBoxItem).filter_by(
        box_id=box_id, image_id=image_id
    ).first()
    if not existing:
        db.add(StorageBoxItem(box_id=box_id, image_id=image_id))
        log_action(db, "add_to_box", image_id, f"添加到储物箱: {box.name}")
    db.commit()
    ref = request.headers.get("Referer", f"/boxes/{box_id}")
    return RedirectResponse(url=ref, status_code=303)


@router.post("/boxes/{box_id}/remove-image")
async def remove_image_from_box(request: Request, box_id: int, db: Session = Depends(get_db)):
    form = await request.form()
    image_id = int(form.get("image_id", "0"))
    if not image_id:
        return JSONResponse({"error": "invalid image_id"}, status_code=400)
    db.query(StorageBoxItem).filter_by(box_id=box_id, image_id=image_id).delete()
    log_action(db, "remove_from_box", image_id, f"从储物箱移除")
    db.commit()
    ref = request.headers.get("Referer", f"/boxes/{box_id}")
    return RedirectResponse(url=ref, status_code=303)


@router.post("/boxes/batch-add")
async def batch_add_to_box(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    box_id = int(form.get("box_id", "0"))
    image_ids = form.getlist("image_ids")
    if not box_id or not image_ids:
        return JSONResponse({"error": "invalid params"}, status_code=400)
    box = db.get(StorageBox, box_id)
    if not box:
        return JSONResponse({"error": "box not found"}, status_code=404)
    for sid in image_ids:
        img_id = int(sid)
        existing = db.query(StorageBoxItem).filter_by(box_id=box_id, image_id=img_id).first()
        if not existing:
            db.add(StorageBoxItem(box_id=box_id, image_id=img_id))
            log_action(db, "add_to_box", img_id, f"批量添加到储物箱: {box.name}")
    db.commit()
    return RedirectResponse(url=form.get("redirect", "/boxes"), status_code=303)


@router.post("/boxes/{box_id}/finalize")
async def finalize_box(request: Request, box_id: int, db: Session = Depends(get_db)):
    """Convert a storage box into a SimilarGroup."""
    box = db.get(StorageBox, box_id)
    if not box:
        return JSONResponse({"error": "box not found"}, status_code=404)
    items = db.execute(
        select(StorageBoxItem).where(StorageBoxItem.box_id == box_id)
    ).scalars().all()
    if not items:
        return JSONResponse({"error": "box is empty"}, status_code=400)
    image_ids = [it.image_id for it in items if it.image]
    if not image_ids:
        return JSONResponse({"error": "no valid images"}, status_code=400)
    group = SimilarGroup(name=box.name, processed=0)
    db.add(group)
    db.flush()
    for img_id in image_ids:
        img = db.get(Image, img_id)
        if img:
            img.similar_group_id = group.id
    # Clear the box
    db.query(StorageBoxItem).filter_by(box_id=box_id).delete()
    db.delete(box)
    log_action(db, "finalize_box", details=f"收纳盒确定分组: {box.name}, {len(image_ids)} 张")
    db.commit()
    return JSONResponse({"success": True, "group_id": group.id})


@router.get("/boxes/data/items")
async def boxes_data_with_items(db: Session = Depends(get_db)):
    """Return all boxes with their image items (for the tray)."""
    boxes = db.execute(
        select(StorageBox).order_by(StorageBox.sort_order, StorageBox.created_at.desc())
    ).scalars().all()
    result = []
    for b in boxes:
        items = db.execute(
            select(StorageBoxItem).where(StorageBoxItem.box_id == b.id)
            .order_by(StorageBoxItem.created_at.desc())
        ).scalars().all()
        item_list = []
        for it in items:
            img = it.image
            if img:
                item_list.append({
                    "id": img.id,
                    "md5_hash": img.md5_hash,
                    "thumb_url": f"/thumbnails/{img.md5_hash}_256.jpg",
                    "lightbox_url": f"/thumbnails/{img.md5_hash}_1024.jpg",
                    "filename": img.original_filename or img.filename or "",
                })
        result.append({
            "id": b.id, "name": b.name, "color": b.color,
            "count": len(item_list), "items": item_list,
        })
    return JSONResponse({"boxes": result})
