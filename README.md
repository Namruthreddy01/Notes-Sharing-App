## Notes Sharing Web App (Phase 1)

Beginner-friendly full-stack app:

- User signup/login
- Upload notes (PDF)
- View notes
- Download notes

### Tech

- FastAPI (Python)
- SQLite (SQLAlchemy ORM)
- Server-rendered pages (Jinja templates)

### Run locally

From the workspace root:

```bash
cd notes-sharing-app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# set a secret key (recommended)
export SECRET_KEY="change-me"

uvicorn app.main:app --reload
```

Then open `http://127.0.0.1:8000`.

### Project structure

- `app/main.py`: routes + HTML pages
- `app/db.py`: DB engine + session
- `app/models.py`: SQLAlchemy models
- `app/auth.py`: password hashing + signed-cookie session helpers
- `app/uploads/`: uploaded PDFs (local dev)
- `app/templates/`: HTML templates
- `app/static/`: CSS
