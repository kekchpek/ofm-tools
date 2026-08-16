# Deploy to Railway (backend) + Cloudflare Pages (frontend)

Step-by-step guide for hosting Content Metadata Changer in production.

## Architecture

```
Browser
  ├─ https://app.example.com          → Cloudflare Pages (React static site)
  └─ https://api.example.com/api/v1/… → Railway (FastAPI + FFmpeg + SQLite + uploads)
```

The frontend calls the API on a **different domain**. Google OAuth callback hits the **API** (Railway), then redirects back to the **frontend** (Cloudflare).

---

## Known limits before you scale

These are deliberate v1 tradeoffs. None of them break a single-instance deploy, but each one bites the moment you add a second replica.

| Limit | Consequence | When it matters |
|-------|-------------|-----------------|
| **Jobs live in process memory** (`api/jobs.py` holds a `dict` and a `ThreadPoolExecutor`) | A restart or crash loses every queued and in-flight job. Clients polling `GET /jobs/{id}` get a 404 afterwards. | Any redeploy. Railway restarts on every deploy. |
| **Jobs are not shared between instances** | A job started on instance A is invisible to instance B, so polling fails intermittently behind a load balancer. | **Run exactly one replica.** Scaling horizontally requires moving jobs to a shared store (Redis/RQ, Celery, or a database-backed queue) first. |
| **Uploads live on local disk** | Files are only reachable from the instance that received them. | Same — one replica, and a persistent volume (see Step 2). |
| **SQLite for users and sessions** | Fine for one writer; concurrent writers from multiple instances will hit lock contention. | Move to Postgres before scaling out. |

Uploaded files are removed after `SESSION_TTL_HOURS`. Cleanup runs at startup and then every `CLEANUP_INTERVAL_MINUTES` (default 60) for as long as the process is alive.

---

## Mobile sign-in: keep the frontend and API on one site

Mobile Safari — and Chrome on iOS, which uses WebKit — block third-party
cookies outright. With the frontend on `*.pages.dev` and the API on
`*.up.railway.app` those are two unrelated sites (both are on the Public Suffix
List), so the session cookie is third-party. Sign-in appears to succeed and then
every request returns 401:

```
GET /api/v1/auth/google/callback … → 307   cookie set
GET /api/v1/auth/me                → 401   cookie not sent back
```

`SameSite=None; Secure` does not help — the browser is refusing, not the server.
Pick one of these:

### Option A — custom domain (recommended)

Put both services under one registrable domain, e.g. `app.example.com` for
Pages and `api.example.com` for Railway. The cookie is then first-party. No
upload size ceiling. See Part 4.

### Option B — proxy /api through Pages

`web/functions/api/[[path]].js` forwards `/api/*` from the Pages origin to
Railway, so the browser only ever talks to one host. Requires no domain.

1. Cloudflare Pages → Settings → Environment variables, add:
   `API_ORIGIN = https://YOUR-RAILWAY-URL.up.railway.app`
2. **Clear** `VITE_API_BASE` (leave it empty) so the app calls its own origin.
3. Redeploy Pages (Vite bakes `VITE_API_BASE` in at build time).
4. Railway: set `GOOGLE_REDIRECT_URI` to
   `https://YOUR-PAGES-URL.pages.dev/api/v1/auth/google/callback`,
   and register that same URL in Google Console.
5. Railway: `AUTH_COOKIE_SAMESITE` may go back to `lax`; `CORS_ORIGINS` becomes
   irrelevant but is harmless to leave.

**Limit:** Cloudflare caps a Worker request body at 100 MB on Free and Pro
plans. Uploads above that will fail through the proxy even though
`MAX_UPLOAD_BYTES` allows 500 MB. If you need large video uploads, use Option A.

---

## Before you start

You need:


| Item                 | Example                                                |
| -------------------- | ------------------------------------------------------ |
| GitHub repo          | This project pushed to GitHub                          |
| Railway account      | [railway.app](https://railway.app)                     |
| Cloudflare account   | [dash.cloudflare.com](https://dash.cloudflare.com)     |
| Google Cloud project | OAuth client (Web application) — you already have this |
| Domain (optional)    | `app.yourdomain.com` + `api.yourdomain.com`            |


**Repo layout note:** If the repo root is `ofm-tools`, set the **root directory** to `content-meta-data-changer` in both Railway and Cloudflare. If the repo root *is* `content-meta-data-changer`, leave root directory empty.

---



## Part 1 — Railway (backend API)



### Step 1: Create a Railway project

1. Go to [railway.app](https://railway.app) → **New Project**.
2. Choose **Deploy from GitHub repo**.
3. Select your repository.
4. If needed, set **Root Directory** to `content-meta-data-changer`.
5. Railway detects the `Dockerfile` and builds the API automatically.



### Step 2: Add persistent storage (volume)

Uploads and the SQLite database must survive redeploys.

1. In your Railway service, open **Volumes**.
2. Click **Add Volume**.
3. Mount path: `/data`
4. Size: start with **1 GB** (increase later if needed).



### Step 3: Generate a public URL

1. Open the service → **Settings** → **Networking**.
2. Click **Generate Domain**.
3. Copy the URL, e.g. `https://content-meta-data-changer-production.up.railway.app`

This is your **API URL** for the rest of the setup.pr

### Step 4: Set environment variables

In Railway → **Variables**, add:


| Variable                 | Value                                                                 | Notes                                                   |
| ------------------------ | --------------------------------------------------------------------- | ------------------------------------------------------- |
| `UPLOAD_DIR`             | `/data/uploads`                                                       | Must be on the volume                                   |
| `DATABASE_PATH`          | `/data/app.db`                                                        | Must be on the volume                                   |
| `CORS_ORIGINS`           | `https://YOUR-PAGES-URL.pages.dev`                                    | Add custom domain later, comma-separated                |
| `FRONTEND_URL`           | `https://YOUR-PAGES-URL.pages.dev`                                    | Where users land after Google sign-in                   |
| `GOOGLE_CLIENT_ID`       | *(from Google Console)*                                               |                                                         |
| `GOOGLE_CLIENT_SECRET`   | *(from Google Console)*                                               | Mark as secret                                          |
| `GOOGLE_REDIRECT_URI`    | `https://YOUR-RAILWAY-URL.up.railway.app/api/v1/auth/google/callback` | Must match Google Console exactly                       |
| `ENABLE_API_DOCS`        | `0`                                                                   | Hides `/docs`, `/redoc`, `/openapi.json` from the public |
| `AUTH_SECRET`            | *(random string)*                                                     | Reserved — nothing is signed with it today              |
| `AUTH_COOKIE_SECURE`     | `1`                                                                   | Required for HTTPS                                      |
| `AUTH_COOKIE_SAMESITE`   | `none`                                                                | Required when frontend and API are on different domains |
| `AUTH_SESSION_TTL_HOURS` | `168`                                                                 | 7 days                                                  |
| `MAX_UPLOAD_BYTES`       | `524288000`                                                           | 500 MB                                                  |
| `SESSION_TTL_HOURS`      | `24`                                                                  | Temp upload cleanup (files in saved pieces are exempt)  |
| `USER_STORAGE_QUOTA_BYTES` | `2147483648`                                                        | Per-user ceiling for saved pieces — size the volume for this x users |
| `JOB_WORKERS`            | `2`                                                                   | Background job threads                                  |


**Do not set** `JOBS_SYNC=1` in production (jobs run in background threads).

Replace placeholders:

- `YOUR-RAILWAY-URL` → Railway public domain from Step 3
- `YOUR-PAGES-URL` → Cloudflare Pages URL (Part 2) — you can update CORS/FRONTEND_URL after Pages is live



### Step 5: Deploy and verify

1. Railway redeploys when variables change.
2. Open:
  ```
   https://YOUR-RAILWAY-URL.up.railway.app/api/v1/health
  ```
3. Expected response:
  ```json
   {"status":"ok"}
  ```
4. Check deploy logs for:
  ```
   Google OAuth is enabled.
     Register this Authorized redirect URI in Google Cloud Console:
       https://...
  ```

---



## Part 2 — Cloudflare Pages (frontend)



### Step 1: Create a Pages project

1. Go to [Cloudflare Dashboard](https://dash.cloudflare.com) → **Workers & Pages** → **Create**.
2. Choose **Pages** → **Connect to Git**.
3. Select the same GitHub repository.
4. Configure build:

  | Setting                    | Value                                                              |
  | -------------------------- | ------------------------------------------------------------------ |
  | **Production branch**      | `main` (or your default branch)                                    |
  | **Root directory**         | `content-meta-data-changer/web` (or `web` if repo root is the app) |
  | **Build command**          | `npm run build`                                                    |
  | **Build output directory** | `dist`                                                             |




### Step 2: Set build environment variable

Under **Environment variables** (Production):


| Variable        | Value                                     |
| --------------- | ----------------------------------------- |
| `VITE_API_BASE` | `https://YOUR-RAILWAY-URL.up.railway.app` |


No trailing slash. This tells the React app where the API lives.

### Step 3: Deploy

1. Click **Save and Deploy**.
2. Wait for the build to finish.
3. Copy your Pages URL, e.g. `https://content-metadata-changer.pages.dev`



### Step 4: Update Railway CORS and frontend URL

Go back to Railway **Variables** and set:

```
CORS_ORIGINS=https://content-metadata-changer.pages.dev
FRONTEND_URL=https://content-metadata-changer.pages.dev
```

If you add a custom domain later, use comma-separated values:

```
CORS_ORIGINS=https://app.yourdomain.com,https://content-metadata-changer.pages.dev
FRONTEND_URL=https://app.yourdomain.com
```

Redeploy Railway after changing variables.

### Step 5: Verify the frontend

1. Open your Pages URL in a browser.
2. Open DevTools → **Network**.
3. Confirm API requests go to your Railway URL (not `localhost`).
4. Test **Sign in with Google** (after Part 3).

**SPA routing:** The repo includes `web/public/_redirects` so routes like `/editor/...` work on refresh.

---



## Part 3 — Google OAuth (production)



### Step 1: Open Google Cloud Console

1. [Google Cloud Console](https://console.cloud.google.com/) → your project.
2. **APIs & Services** → **Credentials**.
3. Open your **Web application** OAuth client.



### Step 2: Authorized redirect URIs

Add **exactly** (HTTPS, no trailing slash):

```
https://YOUR-RAILWAY-URL.up.railway.app/api/v1/auth/google/callback
```

The callback goes to **Railway**, not Cloudflare Pages.

### Step 3: Authorized JavaScript origins

Add your frontend URL(s):

```
https://content-metadata-changer.pages.dev
```

Add custom domain too if you use one:

```
https://app.yourdomain.com
```



### Step 4: OAuth consent screen

- **Testing mode:** only listed test users can sign in.
- **Production mode:** required for public launch (Google may require verification if you request sensitive scopes).

Click **Save** and wait 1–2 minutes.

### Step 5: Test sign-in flow

1. Open the Cloudflare Pages URL.
2. Click **Sign in with Google**.
3. You should redirect to Google → back to Railway callback → back to your Pages URL, signed in.

If sign-in fails:


| Symptom                                      | Fix                                                        |
| -------------------------------------------- | ---------------------------------------------------------- |
| Redirect URI mismatch                        | `GOOGLE_REDIRECT_URI` must match Google Console exactly    |
| CORS error in browser                        | Add Pages URL to `CORS_ORIGINS` on Railway                 |
| Signed in on Google but app shows logged out | Set `AUTH_COOKIE_SECURE=1` and `AUTH_COOKIE_SAMESITE=none` |
| `403 access_denied`                          | Add your Gmail as a test user (Testing mode)               |


---



## Part 4 — Custom domains (recommended — fixes mobile sign-in)



### Cloudflare Pages — `app.yourdomain.com`

1. Pages project → **Custom domains** → **Set up a custom domain**.
2. Enter `app.yourdomain.com`.
3. Cloudflare creates DNS records automatically if the domain is on Cloudflare.



### Railway — `api.yourdomain.com`

1. Railway service → **Settings** → **Networking** → **Custom Domain**.
2. Add `api.yourdomain.com`.
3. Railway shows a CNAME target — add it in Cloudflare DNS:
  - Type: **CNAME**
  - Name: `api`
  - Target: *(Railway-provided value)*
  - Proxy status: **DNS only** (grey cloud), so Railway can issue its own
    TLS certificate. Turning the orange cloud on before the certificate is
    active causes a redirect loop.

You do not buy subdomains. Owning the registrable domain is enough; `app.` and
`api.` are just DNS records you create.



### Update all URLs

After custom domains are active, update:

**Railway variables:**

```
CORS_ORIGINS=https://app.yourdomain.com
FRONTEND_URL=https://app.yourdomain.com
GOOGLE_REDIRECT_URI=https://api.yourdomain.com/api/v1/auth/google/callback
```

**Cloudflare Pages variable:**

```
VITE_API_BASE=https://api.yourdomain.com
```

Remove `API_ORIGIN` if it was set for the Pages proxy — with a custom domain the
proxy is unnecessary, and with it the 100 MB upload ceiling disappears.

**Relax the cookie back to Lax.** `app.example.com` and `api.example.com` are
different origins but the *same site*, so the session cookie is first-party.
That is what makes mobile Safari work, and it means `SameSite=None` is no
longer required:

```
AUTH_COOKIE_SAMESITE=lax
AUTH_COOKIE_SECURE=1
```

CORS is still needed — same site, but different origin — so keep
`CORS_ORIGINS` pointing at the app subdomain.

**Google Console:**

- Redirect URI: `https://api.yourdomain.com/api/v1/auth/google/callback`
- JS origin: `https://app.yourdomain.com`

Redeploy both Railway and Cloudflare Pages after changes.

---



## Part 5 — Post-deploy checklist

- [ ] `GET /api/v1/health` returns `{"status":"ok"}`
- [ ] Frontend loads from Cloudflare Pages
- [ ] Upload a test file (requires sign-in if OAuth enabled)
- [ ] Run transfer / convert job and download result
- [ ] OAuth sign-in and sign-out work
- [ ] Deep link `/editor/...` works after page refresh
- [ ] Railway volume is mounted at `/data`
- [ ] Secrets are only in Railway/Cloudflare dashboards, not in git

---



## Costs (rough estimate)


| Service                | Early stage  |
| ---------------------- | ------------ |
| Railway (API + volume) | ~$5–15/month |
| Cloudflare Pages       | Free         |
| Domain                 | ~$10–15/year |
| Google OAuth           | Free         |


---



## Troubleshooting



### API returns 502 / connection refused

- Check Railway deploy logs.
- Confirm the service listens on `$PORT` (the Dockerfile uses `${PORT:-8080}`).



### Upload fails with 413

- Increase `MAX_UPLOAD_BYTES` or check Railway request size limits on your plan.



### Jobs disappear after redeploy

- Job status is in-memory today. Users may need to re-run jobs after a deploy. Persistent job storage is a future improvement.



### Database or uploads lost after redeploy

- Volume not mounted, or `UPLOAD_DIR` / `DATABASE_PATH` point outside `/data`.



### CORS: “No Access-Control-Allow-Origin”

- `CORS_ORIGINS` must include the exact frontend origin (scheme + host, no path).
- Redeploy Railway after changing.

---



## Quick reference — all production URLs

Replace with your values:


| Purpose        | URL                                                           |
| -------------- | ------------------------------------------------------------- |
| Frontend       | `https://content-metadata-changer.pages.dev`                  |
| API base       | `https://YOUR-APP.up.railway.app`                             |
| Health check   | `https://YOUR-APP.up.railway.app/api/v1/health`               |
| OAuth callback | `https://YOUR-APP.up.railway.app/api/v1/auth/google/callback` |
| Auth config    | `https://YOUR-APP.up.railway.app/api/v1/auth/config`          |


---



## Redeploy workflow


| Change                  | Redeploy                                |
| ----------------------- | --------------------------------------- |
| Backend code / env vars | Railway (auto on git push if connected) |
| Frontend code           | Cloudflare Pages (auto on git push)     |
| `VITE_API_BASE`         | Cloudflare Pages rebuild required       |
| Google OAuth URLs       | Google Console only (no redeploy)       |


