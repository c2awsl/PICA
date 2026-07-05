from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from pica.database import AuditLog

router = APIRouter()


def get_db(request: Request) -> Session:
    engine = request.app.state.engine
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request, db: Session = Depends(get_db)):
    logs = db.execute(
        select(AuditLog).order_by(desc(AuditLog.created_at)).limit(200)
    ).scalars().all()
    return request.app.state.templates.TemplateResponse(
        "audit.html",
        {"request": request, "logs": logs},
    )


@router.get("/audit/data")
async def audit_data(request: Request, db: Session = Depends(get_db)):
    limit = int(request.query_params.get("limit", "100"))
    action = request.query_params.get("action", "")
    query = select(AuditLog).order_by(desc(AuditLog.created_at))
    if action:
        query = query.where(AuditLog.action == action)
    logs = db.execute(query.limit(limit)).scalars().all()
    return JSONResponse([{
        "id": l.id,
        "action": l.action,
        "image_id": l.image_id,
        "details": l.details,
        "created_at": l.created_at.isoformat() if l.created_at else None,
    } for l in logs])
