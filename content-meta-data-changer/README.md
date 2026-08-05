# Content Metadata Changer

Inspect, visualize, transfer, and update metadata for video and image files.

## Desktop app

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py --gui
```

## CLI

```bash
python main.py inspect path/to/file.mov
python main.py layout path/to/file.heic
python main.py payload path/to/file.heic
```

## Web stack

Start both the API and frontend with one command:

```bash
pip install -r requirements.txt -r requirements-api.txt
cd web && npm install && cd ..
./start_server
```

Open `http://localhost:5173`. The Vite dev server proxies `/api` to the API on port 8765.

Options:

```bash
./start_server --api-only
./start_server --web-only
./start_server --help
```

### Manual startup

#### Backend API

```bash
pip install -r requirements.txt -r requirements-dev.txt
export UPLOAD_DIR=data/uploads
export JOBS_SYNC=1
uvicorn api.main:app --reload --port 8765
```

### Frontend

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` to `http://127.0.0.1:8765`.

### Production deploy (Railway + Cloudflare Pages)

See **[docs/DEPLOY_RAILWAY_CLOUDFLARE.md](docs/DEPLOY_RAILWAY_CLOUDFLARE.md)** for a full step-by-step guide.

### Docker Compose

```bash
docker compose up --build
```

- API: `http://localhost:8080/api/v1/health`
- Web dev server: `http://localhost:5173`

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v
bash scripts/qa_web_flow.sh
```

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `UPLOAD_DIR` | `data/uploads` | Temporary uploaded files |
| `JOBS_SYNC` | off | Run jobs synchronously (tests/dev) |
| `MAX_UPLOAD_BYTES` | `524288000` | Upload size limit |
| `CORS_ORIGINS` | localhost:5173 | Allowed browser origins |
| `SESSION_TTL_HOURS` | `24` | Temp file retention target |
| `GOOGLE_CLIENT_ID` | — | Enables Google sign-in when set with secret |
| `GOOGLE_CLIENT_SECRET` | — | Google OAuth client secret (keep in `.env` only) |
| `GOOGLE_REDIRECT_URI` | `http://localhost:5173/api/v1/auth/google/callback` | Must match Google Cloud Console |
| `FRONTEND_URL` | `http://localhost:5173` | Post-login redirect target |
| `DATABASE_PATH` | `data/app.db` | SQLite database for users/sessions |
| `AUTH_SESSION_TTL_HOURS` | `168` | Signed-in session lifetime |
| `AUTH_COOKIE_SECURE` | `0` | Set `1` behind HTTPS in production |
| `AUTH_COOKIE_SAMESITE` | `lax` | Set `none` when frontend and API are on different domains |
| `VITE_API_BASE` | *(empty)* | Cloudflare Pages build: Railway API URL |

Copy `.env.example` to `.env` and fill in Google OAuth credentials. When OAuth env vars are set, uploads and jobs require sign-in.

### Google OAuth setup (fix “doesn't comply with OAuth 2.0 policy”)

1. Open [Google Cloud Console](https://console.cloud.google.com/) → your project.
2. Go to **Google Auth Platform** (or **APIs & Services → Credentials**).
3. Open your **OAuth 2.0 Client ID** (type: Web application).
4. Under **Authorized redirect URIs**, add this **exact** URI:

```
http://localhost:5173/api/v1/auth/google/callback
```

Use `http` (not `https`), no trailing slash. The Vite dev server proxies `/api` to the backend.

5. Under **Authorized JavaScript origins**, add:

```
http://localhost:5173
```

6. Confirm the client type is **Web application** (not Desktop, Android, or iOS).
7. Confirm the **Client ID** in `.env` matches this same OAuth client.
8. On the **OAuth consent screen**, if the app is in **Testing** mode, add your Google account under **Test users**.
9. Click **Save**, wait 1–2 minutes, restart `./start_server`, try sign-in again.

### Common Google Console mistakes

| Problem | Fix |
|---------|-----|
| Redirect URI added under wrong client | Open the client whose ID matches `GOOGLE_CLIENT_ID` in `.env` |
| Client type is not "Web application" | Create a new **Web application** OAuth client |
| Used `https://` or port `8765` | Use `http://localhost:5173/api/v1/auth/google/callback` only |
| App in Testing, user not a test user | Add your Gmail under OAuth consent screen → Test users |
| Edited wrong Google Cloud project | Check project name in console matches where the client was created |

Check the redirect URI the app uses: `GET http://localhost:5173/api/v1/auth/config` → `redirect_uri` field (after starting the server).

## Architecture

- `core/` — shared domain logic used by CLI, API, and workers
- `api/` — FastAPI HTTP service
- `web/` — React SPA
- `gui/` — existing PyQt desktop app
- `docs/WEB_MIGRATION_STRATEGY.md` — full migration plan
