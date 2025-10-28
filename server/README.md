# 3D Building Generator – Local Backend

This folder contains a lightweight FastAPI backend that mocks the core services your iOS app will eventually talk to. It runs completely locally so you can develop and iterate without deploying any cloud infrastructure yet.

## Features

- Auth0-compatible authorization hook (parses `Authorization: Bearer <token>` and extracts the subject claim without verifying the signature – good enough for local use)
- Upload dataset endpoint, which creates a reconstruction job
- Jobs listing and status updates
- Download logging
- JSON file persistence inside `server/data/app_state.json`

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
│   └── storage.py         # Simple JSON-based persistence layer
└── data/
    └── app_state.json     # Created automatically after the first run
```

## Getting Started

1. **Create a virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the development server**
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

4. **Test the API**
   - Open the interactive docs at http://127.0.0.1:8000/docs
   - Supply an `Authorization` header: `Bearer dummy-token` (or copy a real Auth0 access token if you have one)

## Next Steps

- Replace the JSON persistence with a real database (e.g., PostgreSQL + SQLAlchemy / Prisma) when you move to cloud infrastructure.
- Hook the `/jobs/{id}/status` endpoint to your reconstruction workers so progress updates flow back automatically.
- Add file-upload handling and signed URL generation when you are ready to integrate object storage.
