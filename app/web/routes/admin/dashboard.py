from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.admin_auth import require_admin_session
from app.core.database import get_db
from app.services.admin import admin_dashboard_metrics

from .helpers import render_admin


def admin_home(request: Request, db: Session = Depends(get_db), _: bool = Depends(require_admin_session)):
    return render_admin(request, "admin/dashboard.html", {"metrics": admin_dashboard_metrics(db)})
