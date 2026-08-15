"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth import auth_enabled, generate_auth_secret_if_missing, google_redirect_uri
from api.cleanup import run_periodic_cleanup, run_session_cleanup
from api.database import initialize_database
from api.routes import router, service_root

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
generate_auth_secret_if_missing()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    removed = run_session_cleanup()
    if removed:
        print(f"Removed {removed} expired upload session(s)")
    if auth_enabled():
        redirect_uri = google_redirect_uri()
        print("Google OAuth is enabled.")
        print("  Register this Authorized redirect URI in Google Cloud Console:")
        print(f"    {redirect_uri}")
    else:
        print("Google OAuth is not configured — uploads are scoped to an anonymous browser cookie.")
    cleanup_task = asyncio.create_task(run_periodic_cleanup())
    try:
        yield
    finally:
        cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await cleanup_task


def create_app() -> FastAPI:
    app = FastAPI(title="Content Metadata Changer API", version="1.0.0", lifespan=lifespan)
    origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in origins if origin.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, object]:
        return service_root()

    return app


app = create_app()
