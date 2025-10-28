# 3D Building Generator – Local Backend

This folder contains a lightweight FastAPI backend that mocks the core services your iOS app will eventually talk to. It now stores data in a SQLModel-powered database so you can develop locally with PostgreSQL (or temporarily fall back to SQLite) before moving to the cloud.

## Features

- Auth0-compatible authorization hook (parses `Authorization: Bearer <token>` and extracts the subject claim without verifying the signature – good enough for local use)
- Upload dataset endpoint, which creates a reconstruction job
- Jobs listing plus automatic simulated progress updates (queued → processing → meshing → texturing → completed)
- Stores uploaded photo sets on disk (`data/uploads/<job_id>/`) and writes model placeholders to `data/models/`
- Download logging
- SQLModel models mapped to PostgreSQL (or SQLite fallback)
- Optional JSON fallback removed; run against a real database instance for production parity

## Project Layout

```
server/
├── README.md
├── requirements.txt
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI entrypoint
│   ├── auth.py            # Helpers to extract user info from Auth0 tokens
│   ├── schemas.py         # Pydantic models shared across endpoints
│   ├── models.py          # SQLModel table definitions
│   └── storage.py         # Repository layer that talks to the database
├── data/
│   └── .gitignore         # Keeps sqlite fallback out of git
└── .gitignore             # Ignores venv artifacts / sqlite files
```

## Getting Started

1. **Provision a PostgreSQL instance**
   - Quick local option (Docker):
     ```bash
     docker run --name 3dbuilder-postgres \
       -e POSTGRES_PASSWORD=postgres \
       -e POSTGRES_DB=3dbuilder \
       -p 5432:5432 -d postgres:16
     ```
   - Note the connection string: `postgresql+psycopg://postgres:postgres@localhost:5432/3dbuilder`
   - Set it as an environment variable for the backend (`export DATABASE_URL=postgresql+psycopg://...`)
   - If `DATABASE_URL` is unset, the API will fall back to a local SQLite database stored at `data/app.db` for quick smoke tests.

2. **Create a virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the development server**
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

5. **Test the API**
   - Open the interactive docs at http://127.0.0.1:8000/docs
   - Supply an `Authorization` header: `Bearer dummy-token` (or copy a real Auth0 access token if you have one)
   - Call `POST /uploads` (e.g. with curl below) and wait a few seconds; repeated `GET /jobs` shows the job advancing through each stage

   Example curl upload with a local photo:
   ```bash
   curl -H "Authorization: Bearer dummy-token" \\
        -F "dataset_name=Sample" \\
        -F "notes=local test" \\
        -F "files=@/PATH/TO/photo.jpg;type=image/jpeg" \\
        http://127.0.0.1:8000/uploads
   ```

## Next Steps

- When you're ready for production, point `DATABASE_URL` to your managed PostgreSQL instance (RDS, Supabase, Render, etc.).
- Hook the `/jobs/{id}/status` endpoint to your reconstruction workers so progress updates flow back automatically.
- Add file-upload handling and signed URL generation when you are ready to integrate object storage.
