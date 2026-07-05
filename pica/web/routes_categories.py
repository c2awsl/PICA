from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from pica.database import Category, Image, ImageCategory, ImageStatus

router = APIRouter()


def get_db(request: Request) -> Session:
    engine = request.app.state.engine
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()


def _build_tree(categories: list[Category], parent_id: int | None = None) -> list[dict]:
    """Build a nested tree structure from flat category list."""
    tree = []
    for cat in categories:
        if cat.parent_id == parent_id:
            children = _build_tree(categories, cat.id)
            tree.append({
                "id": cat.id,
                "name": cat.name,
                "color": cat.color,
                "parent_id": cat.parent_id,
                "sort_order": cat.sort_order,
                "children": children,
            })
    return sorted(tree, key=lambda x: (x["sort_order"], x["name"]))


@router.get("/categories", response_class=HTMLResponse)
async def categories_page(request: Request, db: Session = Depends(get_db)):
    return request.app.state.templates.TemplateResponse(
        "categories.html",
        {"request": request},
    )


@router.get("/categories/data")
async def categories_data(request: Request, db: Session = Depends(get_db)):
    cats = db.query(Category).order_by(Category.sort_order, Category.name).all()
    tree = _build_tree(cats)
    # Add image counts per category
    counts = {}
    for cat in cats:
        pending = db.query(func.count(ImageCategory.image_id)).filter(
            ImageCategory.category_id == cat.id,
            ImageCategory.source == "confirmed",
            Image.status == ImageStatus.PENDING,
        ).join(Image, ImageCategory.image_id == Image.id).scalar() or 0

        confirmed = db.query(func.count(ImageCategory.image_id)).filter(
            ImageCategory.category_id == cat.id,
            ImageCategory.source == "confirmed",
            Image.status == ImageStatus.CONFIRMED,
        ).join(Image, ImageCategory.image_id == Image.id).scalar() or 0

        total = db.query(func.count(ImageCategory.image_id)).filter(
            ImageCategory.category_id == cat.id,
        ).scalar() or 0

        counts[cat.id] = {"total": total, "pending": pending, "confirmed": confirmed}

    return JSONResponse({"tree": tree, "counts": counts})


@router.post("/categories/create")
async def create_category(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    name = form.get("name", "").strip()
    parent_id = form.get("parent_id")
    if parent_id:
        try:
            parent_id = int(parent_id)
        except (ValueError, TypeError):
            parent_id = None
    color = form.get("color", "#007AFF").strip()

    if not name:
        return JSONResponse({"success": False, "error": "name required"})

    existing = db.query(Category).filter_by(name=name).first()
    if existing:
        return JSONResponse({"success": False, "error": "name already exists"})

    cat = Category(name=name, parent_id=parent_id, color=color)
    db.add(cat)
    db.commit()
    return JSONResponse({"success": True, "id": cat.id})


@router.post("/categories/rename")
async def rename_category(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    cat_id = int(form.get("id", "0"))
    new_name = form.get("name", "").strip()
    if not cat_id or not new_name:
        return JSONResponse({"success": False, "error": "invalid params"})
    cat = db.query(Category).filter_by(id=cat_id).first()
    if not cat:
        return JSONResponse({"success": False, "error": "not found"})
    cat.name = new_name
    db.commit()
    return JSONResponse({"success": True})


@router.post("/categories/move")
async def move_category(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    cat_id = int(form.get("id", "0"))
    new_parent_id = form.get("parent_id")
    if new_parent_id:
        try:
            new_parent_id = int(new_parent_id)
        except (ValueError, TypeError):
            new_parent_id = None
    if not cat_id:
        return JSONResponse({"success": False, "error": "invalid id"})
    cat = db.query(Category).filter_by(id=cat_id).first()
    if not cat:
        return JSONResponse({"success": False, "error": "not found"})
    cat.parent_id = new_parent_id
    db.commit()
    return JSONResponse({"success": True})


@router.post("/categories/reorder")
async def reorder_category(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    cat_id = int(form.get("id", "0"))
    sort_order = int(form.get("sort_order", "0"))
    if not cat_id:
        return JSONResponse({"success": False, "error": "invalid id"})
    cat = db.query(Category).filter_by(id=cat_id).first()
    if not cat:
        return JSONResponse({"success": False, "error": "not found"})
    cat.sort_order = sort_order
    db.commit()
    return JSONResponse({"success": True})


@router.post("/categories/delete")
async def delete_category(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    cat_id = int(form.get("id", "0"))
    if not cat_id:
        return JSONResponse({"success": False, "error": "invalid id"})
    cat = db.query(Category).filter_by(id=cat_id).first()
    if not cat:
        return JSONResponse({"success": False, "error": "not found"})
    # Remove links
    db.query(ImageCategory).filter_by(category_id=cat_id).delete()
    # Reparent children
    for child in cat.children:
        child.parent_id = cat.parent_id
    db.delete(cat)
    db.commit()
    return JSONResponse({"success": True})
