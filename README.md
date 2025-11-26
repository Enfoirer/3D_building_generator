# 3D Building Generator

SwiftUI client + FastAPI backend for uploading 2D photos and tracking 3D reconstruction jobs. The backend can simulate progress locally or call an external reconstruction service; artifacts can be stored on disk or uploaded to Supabase Storage.

## Project layout
- `3D_building_generator/`: iOS app (SwiftUI, Auth0 login, upload, polling, real download/share)
- `server/`: FastAPI backend (SQLModel, Postgres/Supabase, reconstruction callbacks, artifact download)
- `docs/`: design notes and service interface

## Quick start (local)
1) Backend dependencies
```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
2) Environment vars (fill at least `DATABASE_URL`; optional Supabase + reconstruction settings)
```bash
set -a; source .env.local; set +a
```
3) Run backend
```bash
uvicorn app.main:app --reload --port 8000
```
- Simulated progress: `RECONSTRUCTION_ALLOW_SIMULATION=1` (default)
- External recon: set `RECON_SERVICE_URL`, `RECON_SERVICE_TOKEN`, `RECON_CALLBACK_TOKEN`; service posts to `/internal/reconstruction/status`
4) iOS app
   - Open `3D_building_generator.xcodeproj`, ensure `Environment.API.baseURL` points to the backend (default `http://127.0.0.1:8000`)
   - Run on simulator/device, log in, upload photos, wait for completion, tap Download to fetch/share the model

## Key backend endpoints
- `POST /uploads` create job from photos
- `GET /jobs` / `GET /jobs/{id}` list or fetch job status
- `GET /jobs/{id}/artifact` download model (redirects with signed URL if stored in Supabase)
- `POST /internal/reconstruction/status` status/artifact callback (requires `RECON_CALLBACK_TOKEN`)

## Common environment variables
- Database: `DATABASE_URL` (Postgres or SQLite)
- Reconstruction: `RECON_SERVICE_URL`, `RECON_SERVICE_TOKEN`, `RECON_CALLBACK_TOKEN`, `RECONSTRUCTION_ALLOW_SIMULATION`
- Storage (optional Supabase Storage): `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_STORAGE_BUCKET`
- Other: `RECONSTRUCTION_COMMAND` (local pipeline), `RECONSTRUCTION_ARTIFACT_PATTERN` (artifact glob)

## Deploying (outline)
- Backend to a host with persistent storage (Render/Fly/Railway/Heroku+disk), mount `server/data` or use Supabase Storage.
- Database: cloud Postgres (e.g., Supabase); set `DATABASE_URL`.
- iOS: set `Environment.API.baseURL` to your domain; add the domain to Auth0 callback allowlist.

## Demo path
Local backend with simulation → upload in the app → observe status → download/share the produced model.
