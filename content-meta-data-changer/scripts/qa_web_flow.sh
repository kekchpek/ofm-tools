#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
fi

export UPLOAD_DIR="${UPLOAD_DIR:-$ROOT/data/uploads}"
export JOBS_SYNC=1

"$PYTHON" -m pytest tests/ -v --ignore=tests/e2e

if [[ -f "../OfmContent/TikTok/Video/video6.mov" ]]; then
  "$PYTHON" - <<'PY'
from pathlib import Path
from httpx import ASGITransport, AsyncClient
import asyncio
from api.main import app

async def main():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        session = (await client.post("/api/v1/sessions")).json()["session_id"]
        path = Path("../OfmContent/TikTok/Video/video6.mov")
        with path.open("rb") as handle:
            uploaded = await client.post(
                f"/api/v1/sessions/{session}/files",
                files={"file": (path.name, handle, "application/octet-stream")},
            )
        uploaded.raise_for_status()
        file_id = uploaded.json()["file_id"]
        metadata = await client.get(f"/api/v1/files/{file_id}/metadata")
        assert metadata.status_code == 200
        print("QA upload + metadata OK")

asyncio.run(main())
PY
fi

echo "QA complete."
