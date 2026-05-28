from __future__ import annotations

import os
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from . import auth
from .db import engine, get_db
from .models import Base, Note, User


APP_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = APP_DIR / "uploads"


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_note_dashboard_columns()


def _ensure_note_dashboard_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("notes"):
        return

    existing = {column["name"] for column in inspector.get_columns("notes")}
    columns = {
        "description": "TEXT",
        "note_department": "VARCHAR(120)",
        "subject_name": "VARCHAR(120)",
        "unit_name": "VARCHAR(120)",
    }
    with engine.begin() as connection:
        for column_name, column_type in columns.items():
            if column_name not in existing:
                connection.execute(text(f"ALTER TABLE notes ADD COLUMN {column_name} {column_type}"))


app = FastAPI(title="Notes Sharing App")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


@app.on_event("startup")
def _startup() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    init_db()


def _set_session_cookie(response: RedirectResponse, user_id: int) -> None:
    token = auth.sign_session(user_id)
    response.set_cookie(
        auth.SESSION_COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=False,  # set True behind HTTPS
        max_age=60 * 60 * 24 * 7,
    )


def _clear_session_cookie(response: RedirectResponse) -> None:
    response.delete_cookie(auth.SESSION_COOKIE_NAME)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    user_id = auth.read_session(request.cookies.get(auth.SESSION_COOKIE_NAME))
    if not user_id:
        raise HTTPException(status_code=401)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401)
    return user


def _require_login_redirect(request: Request) -> RedirectResponse:
    return RedirectResponse(url=f"/login?next={request.url.path}", status_code=303)


def _clean_optional_text(value: str, max_length: int) -> Optional[str]:
    value_clean = value.strip()
    if not value_clean:
        return None
    return value_clean[:max_length]


def _display_name(user: User) -> str:
    return user.display_name or user.email.split("@")[0]


def _group_notes_for_dashboard(notes: list[Note]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, dict[str, list[Note]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for note in notes:
        department = note.note_department or "General"
        subject = note.subject_name or "Unsorted subject"
        unit = note.unit_name or "Unsorted unit"
        grouped[department][subject][unit].append(note)

    dashboard_groups = []
    for department, subjects in sorted(grouped.items()):
        subject_groups = []
        department_total = 0
        for subject, units in sorted(subjects.items()):
            unit_groups = []
            subject_total = 0
            for unit, unit_notes in sorted(units.items()):
                unit_groups.append({"name": unit, "notes": unit_notes, "count": len(unit_notes)})
                subject_total += len(unit_notes)
            subject_groups.append({"name": subject, "units": unit_groups, "count": subject_total})
            department_total += subject_total
        dashboard_groups.append({"name": department, "subjects": subject_groups, "count": department_total})
    return dashboard_groups


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("signup.html", {"request": request, "error": None})


@app.post("/signup")
def signup_action(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(default=""),
    department: str = Form(default=""),
    college: str = Form(default=""),
    db: Session = Depends(get_db),
):
    email_norm = email.strip().lower()
    if "@" not in email_norm or len(password) < 6:
        return templates.TemplateResponse(
            "signup.html",
            {"request": request, "error": "Use a valid email and a password of 6+ characters."},
            status_code=400,
        )

    existing = db.execute(select(User).where(User.email == email_norm)).scalar_one_or_none()
    if existing:
        return templates.TemplateResponse(
            "signup.html",
            {"request": request, "error": "Email already registered. Please log in."},
            status_code=400,
        )

    user = User(
        email=email_norm,
        password_hash=auth.hash_password(password),
        display_name=_clean_optional_text(display_name, 120),
        department=_clean_optional_text(department, 120),
        college=_clean_optional_text(college, 160),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    resp = RedirectResponse(url="/", status_code=303)
    _set_session_cookie(resp, user.id)
    return resp


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: Optional[str] = None) -> HTMLResponse:
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "next": next})


@app.post("/login")
def login_action(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/"),
    db: Session = Depends(get_db),
):
    email_norm = email.strip().lower()
    user = db.execute(select(User).where(User.email == email_norm)).scalar_one_or_none()
    if not user or not auth.verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid email or password.", "next": next},
            status_code=400,
        )

    dest = next if (next and next.startswith("/")) else "/"
    resp = RedirectResponse(url=dest, status_code=303)
    _set_session_cookie(resp, user.id)
    return resp


@app.post("/logout")
def logout_action() -> RedirectResponse:
    resp = RedirectResponse(url="/login", status_code=303)
    _clear_session_cookie(resp)
    return resp


@app.get("/profile", response_class=HTMLResponse)
def profile_page(
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        user = get_current_user(request, db)
    except HTTPException:
        return _require_login_redirect(request)

    note_count = db.execute(select(Note).where(Note.owner_id == user.id)).scalars().all()
    return templates.TemplateResponse(
        "profile.html",
        {"request": request, "user": user, "note_count": len(note_count), "saved": False, "error": None},
    )


@app.post("/profile", response_class=HTMLResponse)
def profile_action(
    request: Request,
    display_name: str = Form(default=""),
    department: str = Form(default=""),
    college: str = Form(default=""),
    db: Session = Depends(get_db),
):
    try:
        user = get_current_user(request, db)
    except HTTPException:
        return _require_login_redirect(request)

    user.display_name = _clean_optional_text(display_name, 120)
    user.department = _clean_optional_text(department, 120)
    user.college = _clean_optional_text(college, 160)
    db.commit()
    db.refresh(user)

    note_count = db.execute(select(Note).where(Note.owner_id == user.id)).scalars().all()
    return templates.TemplateResponse(
        "profile.html",
        {"request": request, "user": user, "note_count": len(note_count), "saved": True, "error": None},
    )


@app.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        user = get_current_user(request, db)
    except HTTPException:
        return _require_login_redirect(request)

    notes = (
        db.execute(select(Note).where(Note.owner_id == user.id).order_by(Note.uploaded_at.desc()))
        .scalars()
        .all()
    )
    recent_notes = notes[:5]
    dashboard_groups = _group_notes_for_dashboard(notes)
    subjects = {note.subject_name for note in notes if note.subject_name}
    units = {note.unit_name for note in notes if note.unit_name}
    dashboard_stats = {
        "notes": len(notes),
        "departments": len(dashboard_groups),
        "subjects": len(subjects),
        "units": len(units),
    }
    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "user": user,
            "notes": notes,
            "recent_notes": recent_notes,
            "dashboard_groups": dashboard_groups,
            "dashboard_stats": dashboard_stats,
            "display_name": _display_name(user),
        },
    )


@app.get("/upload", response_class=HTMLResponse)
def upload_page(
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        user = get_current_user(request, db)
    except HTTPException:
        return _require_login_redirect(request)

    return templates.TemplateResponse("upload.html", {"request": request, "user": user, "error": None})


@app.post("/upload")
async def upload_action(
    request: Request,
    title: str = Form(...),
    description: str = Form(default=""),
    note_department: str = Form(default=""),
    subject_name: str = Form(default=""),
    unit_name: str = Form(default=""),
    pdf: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    try:
        user = get_current_user(request, db)
    except HTTPException:
        return _require_login_redirect(request)

    title_clean = title.strip()
    if not title_clean:
        return templates.TemplateResponse(
            "upload.html",
            {"request": request, "user": user, "error": "Title is required."},
            status_code=400,
        )

    filename = (pdf.filename or "").strip()
    content_type = (pdf.content_type or "").lower()
    if not filename.lower().endswith(".pdf") or "pdf" not in content_type:
        return templates.TemplateResponse(
            "upload.html",
            {"request": request, "user": user, "error": "Please upload a PDF file."},
            status_code=400,
        )

    stored_filename = f"{uuid.uuid4().hex}.pdf"
    stored_path = UPLOADS_DIR / stored_filename

    data = await pdf.read()
    if len(data) > 25 * 1024 * 1024:
        return templates.TemplateResponse(
            "upload.html",
            {"request": request, "user": user, "error": "File too large (max 25MB)."},
            status_code=400,
        )

    stored_path.write_bytes(data)

    note = Note(
        owner_id=user.id,
        title=title_clean,
        original_filename=filename,
        stored_filename=stored_filename,
        description=_clean_optional_text(description, 500),
        note_department=_clean_optional_text(note_department, 120) or user.department,
        subject_name=_clean_optional_text(subject_name, 120),
        unit_name=_clean_optional_text(unit_name, 120),
    )
    db.add(note)
    db.commit()
    db.refresh(note)

    return RedirectResponse(url=f"/notes/{note.id}", status_code=303)


def _get_note_owned_or_404(db: Session, note_id: int, owner_id: int) -> Note:
    note = db.get(Note, note_id)
    if not note or note.owner_id != owner_id:
        raise HTTPException(status_code=404)
    return note


@app.get("/notes/{note_id}", response_class=HTMLResponse)
def note_detail_page(
    note_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        user = get_current_user(request, db)
    except HTTPException:
        return _require_login_redirect(request)

    note = _get_note_owned_or_404(db, note_id, user.id)
    return templates.TemplateResponse("note_detail.html", {"request": request, "user": user, "note": note})


@app.get("/notes/{note_id}/file")
def note_file_inline(
    note_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        user = get_current_user(request, db)
    except HTTPException:
        return _require_login_redirect(request)

    note = _get_note_owned_or_404(db, note_id, user.id)
    path = UPLOADS_DIR / note.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(
        path=str(path),
        media_type="application/pdf",
        filename=note.original_filename,
    )


@app.get("/notes/{note_id}/download")
def note_download(
    note_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        user = get_current_user(request, db)
    except HTTPException:
        return _require_login_redirect(request)

    note = _get_note_owned_or_404(db, note_id, user.id)
    path = UPLOADS_DIR / note.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404)

    headers = {"Content-Disposition": f'attachment; filename="{note.original_filename}"'}
    return FileResponse(path=str(path), media_type="application/pdf", headers=headers)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "env": os.environ.get("ENV", "dev")}
