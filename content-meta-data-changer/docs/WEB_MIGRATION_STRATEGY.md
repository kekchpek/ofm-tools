# Web Migration Strategy — Content Metadata Changer

This document is the **authoritative plan** for migrating the desktop application to a web product. It is written so that an **AI coding agent** (or a human developer) can execute it milestone-by-milestone with verifiable acceptance criteria and automated tests at every step.

---

## Table of contents

1. [Purpose and scope](#1-purpose-and-scope)
2. [Current architecture snapshot](#2-current-architecture-snapshot)
3. [Target architecture](#3-target-architecture)
4. [Guiding principles](#4-guiding-principles)
5. [Repository layout after migration](#5-repository-layout-after-migration)
6. [Milestones overview](#6-milestones-overview)
7. [Milestone M0 — Test harness and fixtures](#7-milestone-m0--test-harness-and-fixtures)
8. [Milestone M1 — Core extraction](#8-milestone-m1--core-extraction)
9. [Milestone M2 — HTTP API (read-only)](#9-milestone-m2--http-api-read-only)
10. [Milestone M3 — Web frontend (read-only editor)](#10-milestone-m3--web-frontend-read-only-editor)
11. [Milestone M4 — Background jobs (transfer, convert, preview)](#11-milestone-m4--background-jobs-transfer-convert-preview)
12. [Milestone M5 — Web frontend (full parity)](#12-milestone-m5--web-frontend-full-parity)
13. [Milestone M6 — Production hardening](#13-milestone-m6--production-hardening)
14. [API specification](#14-api-specification)
15. [Data transfer objects (DTOs)](#15-data-transfer-objects-dtos)
16. [Testing strategy](#16-testing-strategy)
17. [Agent execution protocol](#17-agent-execution-protocol)
18. [Risk register](#18-risk-register)
19. [Out of scope for v1 web](#19-out-of-scope-for-v1-web)
20. [Appendix A — Fixture inventory](#20-appendix-a--fixture-inventory)
21. [Appendix B — Command reference](#21-appendix-b--command-reference)

---

## 1. Purpose and scope

### 1.1 Goal

Deliver a **browser-based** version of Content Metadata Changer that supports:

| Feature | Desktop today | Web v1 target |
|---------|----------------|---------------|
| File library (add / open / remove) | Yes | Yes (upload-based) |
| Metadata panel | Yes | Yes |
| Memory layout map + segment inspector | Yes | Yes |
| Unknown headers / unknown memory | Yes | Yes |
| Metadata transfer | Yes | Yes (async job + download) |
| Video / image conversion | Yes | Yes (async job + download) |
| Update Finder preview (artwork) | Yes | Yes (async job + download) |
| Drag-and-drop to library | Yes | Yes (browser dropzone) |
| In-place file edit on disk | Yes | **No** — always produce downloadable output |
| CLI | Yes | Yes (unchanged, shares core) |

### 1.2 Non-goals for v1 web

- Pure client-side / WASM-only processing (no upload)
- User accounts, billing, multi-tenant SaaS (unless added in M6+)
- Mobile-native apps
- Rewriting layout parsers in TypeScript

### 1.3 Success definition

Web v1 is complete when:

1. All acceptance criteria in **M0–M6** pass.
2. Full **pytest** suite passes locally and in CI.
3. An agent can run **Appendix B** commands end-to-end without manual steps.
4. A user can upload files from `OfmContent/`, inspect them, transfer metadata, convert, update preview, and download results.

---

## 2. Current architecture snapshot

### 2.1 Portable core (reuse on web backend)

| Module | Responsibility |
|--------|----------------|
| `formats/` | Metadata formatting (MOV, MP4, JPEG, PNG, HEIC) |
| `layout/` | Binary layout parsers (QuickTime, JPEG, PNG, HEIF) |
| `layout/atom_graft.py` | QuickTime metadata atom grafting |
| `layout/atom_database.py` | Atom descriptions + edit safety (SQLite) |
| `metadata_transfer.py` | Transfer orchestration (video graft + image EXIF) |
| `video_preview.py` | Embed first-frame JPEG as Finder artwork |
| `conversion.py` | FFmpeg video conversion |
| `image_conversion.py` | Pillow image conversion |
| `media_types.py` | Extension / kind helpers |
| `cli.py` | CLI (should call core, not duplicate logic) |

### 2.2 Desktop-only (rewrite for web)

| Module | Responsibility |
|--------|----------------|
| `gui/library_window.py` | File library UI |
| `gui/editor_window.py` | Editor (preview + metadata + layout) |
| `gui/metadata_transfer_window.py` | Transfer wizard |
| `gui/common.py` | PyQt widgets, workers |
| `layout/widget.py` | Interactive memory layout canvas |
| `layout/*_dialog.py` | Modal dialogs |

### 2.3 External dependencies

| Dependency | Used for | Web backend |
|------------|----------|-------------|
| FFmpeg (system) | Video conversion | Required in Docker worker |
| OpenCV | First-frame extraction | Required in worker |
| Pillow + pillow-heif | Images / HEIC | Required in API/worker |
| mutagen | MP4 tags (post-graft) | Required in worker |
| SQLite | Atom DB | Ship with container |
| PyQt6 | Desktop GUI | **Not used on web** |

---

## 3. Target architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Browser SPA (React + TypeScript recommended)               │
│  - Library page                                             │
│  - Editor page (preview | metadata | layout map)            │
│  - Job progress + download                                  │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTPS / JSON
┌──────────────────────────▼──────────────────────────────────┐
│  API service (FastAPI)                                      │
│  - Upload session management                                │
│  - Inspect endpoints (sync, fast)                           │
│  - Job creation + status                                    │
└──────────────┬─────────────────────────────┬────────────────┘
               │                             │
┌──────────────▼──────────────┐   ┌──────────▼─────────────────┐
│  Worker service             │   │  Storage                   │
│  - transfer_metadata        │   │  - temp upload dir or S3   │
│  - convert_video/image      │   │  - TTL cleanup cron        │
│  - update_video_preview     │   │  - Postgres/SQLite jobs DB │
│  - FFmpeg, OpenCV, Pillow   │   └────────────────────────────┘
└─────────────────────────────┘
               │
┌──────────────▼──────────────┐
│  core/ (shared Python pkg)    │
│  - inspect, transfer, convert│
│  - same logic as CLI          │
└───────────────────────────────┘
```

### 3.1 Sync vs async operations

| Operation | Mode | Reason |
|-----------|------|--------|
| Upload file | Sync (multipart) | Standard HTTP |
| Read metadata | Sync | Fast (< 2 s on fixtures) |
| Parse layout | Sync | Fast |
| Segment hex preview | Sync | Reads ≤ 512 bytes |
| Preview image (JPEG) | Sync | Single frame / image |
| Metadata transfer | **Async job** | Rewrites whole file |
| Conversion | **Async job** | FFmpeg can take minutes |
| Update preview | **Async job** | Reads video + rewrites moov |

---

## 4. Guiding principles

1. **Single core library** — CLI, API, and workers call the same functions.
2. **Never overwrite uploads** — web always produces a **new output file** for mutation operations.
3. **Test-first milestones** — no milestone is done until pytest (and specified E2E checks) pass.
4. **Fixture-driven** — use existing files under `OfmContent/`; add minimal synthetic fixtures only when needed.
5. **Agent-verifiable** — every task has concrete file paths, commands, and expected outputs.
6. **Privacy by default** — temp files expire; document retention policy in README.

---

## 5. Repository layout after migration

Target structure (create incrementally; do not big-bang move):

```
content-meta-data-changer/
├── core/                          # NEW — domain layer
│   ├── __init__.py
│   ├── models.py                  # Pydantic DTOs
│   ├── inspect.py                 # metadata + layout + segment bytes
│   ├── transfer.py
│   ├── convert.py
│   ├── preview.py
│   └── errors.py                  # unified exceptions
├── api/                           # NEW — FastAPI app
│   ├── __init__.py
│   ├── main.py
│   ├── routes/
│   │   ├── sessions.py
│   │   ├── files.py
│   │   └── jobs.py
│   ├── storage.py                 # local disk abstraction
│   ├── jobs.py                    # job queue interface
│   └── worker.py                  # job executor entrypoint
├── web/                           # NEW — frontend SPA
│   ├── package.json
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   └── api/
│   └── tests/                     # Playwright or Vitest
├── tests/                         # NEW — Python tests
│   ├── conftest.py
│   ├── fixtures/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── docs/
│   └── WEB_MIGRATION_STRATEGY.md  # this file
├── formats/                       # existing — import from core
├── layout/                        # existing
├── gui/                           # keep for desktop
├── cli.py                         # refactor to use core/
└── requirements-dev.txt           # NEW — pytest, httpx, etc.
```

---

## 6. Milestones overview

| ID | Name | Duration (est.) | Depends on | Delivers |
|----|------|-----------------|------------|----------|
| **M0** | Test harness + fixtures | 2–3 days | — | pytest infra, fixture map |
| **M1** | Core extraction | 4–5 days | M0 | `core/` package, CLI uses it |
| **M2** | HTTP API read-only | 4–5 days | M1 | Upload + inspect endpoints |
| **M3** | Web UI read-only | 5–7 days | M2 | Browser editor (no jobs) |
| **M4** | Background jobs | 5–7 days | M2 | Transfer / convert / preview |
| **M5** | Web UI full parity | 5–7 days | M3, M4 | Transfer wizard, toolbar |
| **M6** | Production hardening | 5–7 days | M5 | Docker, CI, cleanup, limits |

**Total estimate:** 10–14 weeks for one developer; an agent can parallelize tests while building.

---

## 7. Milestone M0 — Test harness and fixtures

### 7.1 Objectives

- Introduce pytest without changing product behavior.
- Document and validate all test media paths.
- Establish patterns every later milestone copies.

### 7.2 Agent tasks

#### M0-T1 — Add dev dependencies

Create `requirements-dev.txt`:

```
pytest>=8.0
pytest-cov>=5.0
httpx>=0.27          # API tests (M2+)
anyio>=4.0           # async test support
```

Add to `requirements-dev.txt` later milestones: `fastapi`, `uvicorn`, `python-multipart`.

**Do not** add PyQt to dev deps.

#### M0-T2 — Create test layout

```
tests/
├── conftest.py
├── unit/
│   └── test_smoke_fixtures.py
├── integration/
│   └── (empty placeholder)
└── e2e/
    └── (empty placeholder)
```

#### M0-T3 — Implement `tests/conftest.py`

Must expose these pytest fixtures:

| Fixture name | Returns | Notes |
|--------------|---------|-------|
| `repo_root` | `Path` | `content-meta-data-changer/` |
| `ofm_content` | `Path` | `../OfmContent` resolved |
| `video6_target` | `Path` | `OfmContent/TikTok/Video/video6.mov` |
| `video6_source` | `Path` | `OfmContent/TikTok/Video/video6_meta_source.mov` |
| `video6_output` | `Path` | `video6_with_metadata.mov` (if exists) |
| `heic_source` | `Path` | `avatar_meta_data_source.HEIC` |
| `tmp_media` | `Path` | `tmp_path / "media"` directory |

Skip fixtures gracefully with `pytest.skip()` if a file is missing (agent should log which fixtures are absent).

#### M0-T4 — Smoke tests

Create `tests/unit/test_smoke_fixtures.py`:

- Assert each fixture path that exists is a file.
- Assert `parse_file_layout(video6_target)` returns segments.
- Assert `format_metadata(video6_target)` is non-empty string.
- Assert `supported_extensions()` includes `.mov`, `.heic`.

### 7.3 Acceptance criteria (M0)

- [ ] `pytest tests/ -v` exits 0.
- [ ] At least 4 smoke tests pass when `OfmContent/` is present.
- [ ] Missing optional fixtures skip rather than fail the whole suite.
- [ ] No changes to GUI behavior.

### 7.4 Agent verification command

```bash
cd content-meta-data-changer
python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/pytest tests/ -v --tb=short
```

---

## 8. Milestone M1 — Core extraction

### 8.1 Objectives

Create `core/` as the single domain entry point. Refactor CLI to use it without changing CLI output.

### 8.2 Core API surface

Implement in `core/`:

```python
# core/models.py — Pydantic v2 models (see Section 15)

# core/inspect.py
def inspect_metadata(path: Path) -> MetadataResult: ...
def inspect_layout(path: Path) -> LayoutResult: ...
def inspect_segment_bytes(path: Path, offset: int, size: int, *, limit: int = 512) -> bytes: ...
def inspect_preview_jpeg(path: Path) -> bytes: ...
def inspect_summary(path: Path) -> InspectSummary: ...

# core/transfer.py
def transfer_metadata_files(target: Path, source: Path, destination: Path) -> Path: ...

# core/convert.py
def convert_video_file(source: Path, destination: Path, target_key: str) -> Path: ...
def convert_image_file(source: Path, destination: Path, target_key: str) -> Path: ...

# core/preview.py
def update_embedded_preview(path: Path) -> None: ...  # in-place; API wraps with copy

# core/errors.py
class CoreError(Exception): ...
class UnsupportedMediaError(CoreError): ...
class LayoutError(CoreError): ...
class TransferError(CoreError): ...
class ConversionError(CoreError): ...
class PreviewError(CoreError): ...
```

Wrap existing exceptions (`MetadataTransferError`, `LayoutParseError`, etc.) — do not break string messages.

### 8.3 Agent tasks

#### M1-T1 — Create `core/models.py`

Map from existing types:

- `layout.base.FileSegment` → `SegmentDTO`
- `layout.base.FileLayout` → `LayoutResult`
- Metadata text → structured `MetadataResult` **and** keep `.as_text()` for CLI compatibility.

#### M1-T2 — Implement `core/inspect.py`

Delegate to:

- `metadata.format_metadata`
- `layout.parse_file_layout`
- `layout.heif.format_payload_metadata_report` (optional helper endpoint later)
- `gui.common.read_first_frame` logic moved to core (remove OpenCV import from GUI over time).

**Important:** `inspect_preview_jpeg` must work for video and image paths.

#### M1-T3 — Implement `core/transfer.py`, `core/convert.py`, `core/preview.py`

Thin wrappers around existing modules.

#### M1-T4 — Refactor `cli.py`

Replace direct imports with `core.*` calls. **CLI output must remain byte-identical** on fixtures (see tests).

#### M1-T5 — Unit tests

| Test file | Covers |
|-----------|--------|
| `tests/unit/test_core_inspect.py` | metadata, layout segment count, categories |
| `tests/unit/test_core_transfer.py` | video6 transfer produces output; HEIC transfer |
| `tests/unit/test_core_convert.py` | skip if no ffmpeg |
| `tests/unit/test_core_preview.py` | artwork key appears in moov/meta after update |
| `tests/unit/test_cli_parity.py` | CLI vs core text output |

#### M1-T6 — CLI parity test details

For each fixture in Appendix A:

```python
assert cli_run(["metadata", path]) == core.inspect_metadata(path).as_text()
assert cli_run(["layout", path]) == core.inspect_layout(path).as_text()
```

Allow trailing newline normalization only.

### 8.4 Acceptance criteria (M1)

- [ ] `core/` importable without PyQt6 installed.
- [ ] `pytest tests/unit/test_core_*.py -v` passes.
- [ ] CLI parity tests pass.
- [ ] Desktop GUI still runs (smoke: import `gui`).

### 8.5 Agent verification command

```bash
.venv/bin/pytest tests/unit/ -v
.venv/bin/python main.py inspect ../OfmContent/TikTok/Video/video6.mov
.venv/bin/python -c "from core.inspect import inspect_layout; print(len(inspect_layout('../OfmContent/TikTok/Video/video6.mov').segments))"
```

---

## 9. Milestone M2 — HTTP API (read-only)

### 9.1 Objectives

FastAPI service: upload files, return metadata/layout/preview JSON and bytes.

### 9.2 Agent tasks

#### M2-T1 — Add API dependencies

Append to `requirements-dev.txt` (and create `requirements-api.txt` for prod):

```
fastapi>=0.115
uvicorn[standard]>=0.30
python-multipart>=0.0.9
pydantic>=2.0
```

#### M2-T2 — Implement storage layer

`api/storage.py`:

- `create_session() -> session_id`
- `save_upload(session_id, file_id, filename, bytes) -> StoredFile`
- `resolve_path(session_id, file_id) -> Path`
- `delete_session(session_id)`
- Base dir: `data/uploads/` (gitignored)

#### M2-T3 — Implement routes

See [Section 14](#14-api-specification) for full contract.

Minimum routes:

| Method | Path |
|--------|------|
| `POST` | `/api/v1/sessions` |
| `POST` | `/api/v1/sessions/{session_id}/files` |
| `GET` | `/api/v1/files/{file_id}/metadata` |
| `GET` | `/api/v1/files/{file_id}/layout` |
| `GET` | `/api/v1/files/{file_id}/segments/{offset}` |
| `GET` | `/api/v1/files/{file_id}/preview.jpg` |
| `GET` | `/api/v1/health` |

#### M2-T4 — Integration tests

`tests/integration/test_api_readonly.py` using `httpx.AsyncClient` + FastAPI lifespan:

1. Create session.
2. Upload `video6.mov`.
3. GET metadata → 200, contains `"Format: MOV"`.
4. GET layout → 200, `segments` length > 0, includes `mdat`.
5. GET preview.jpg → 200, `Content-Type: image/jpeg`, body starts with `FF D8 FF`.
6. GET segment at known offset → hex string length > 0.

Use `ASGITransport` — no need for live server in CI.

#### M2-T5 — OpenAPI schema

FastAPI auto-generates `/docs`. Agent must verify schemas match Section 15 DTOs.

### 9.3 Acceptance criteria (M2)

- [ ] `uvicorn api.main:app` starts without error.
- [ ] Integration tests pass without PyQt6.
- [ ] Upload + inspect flow works for `.mov`, `.heic`, `.jpg`.
- [ ] 404 for unknown file_id; 422 for bad offset.

### 9.4 Agent verification command

```bash
.venv/bin/pytest tests/integration/test_api_readonly.py -v
.venv/bin/uvicorn api.main:app --port 8765 &
curl -s http://127.0.0.1:8765/api/v1/health
# manual: follow README snippet for upload flow
```

---

## 10. Milestone M3 — Web frontend (read-only editor)

### 10.1 Objectives

SPA that uploads a file and shows preview, metadata text, and memory layout map.

### 10.2 Tech choices (recommended)

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | React 18 + TypeScript | Large ecosystem, agent-friendly |
| Build | Vite | Fast dev |
| HTTP | fetch or axios | Simple |
| Layout map | Canvas 2D | Matches current bar visualization |
| Tests | Vitest + Playwright | Unit + E2E |

Agent may substitute SvelteKit if documented, but must meet same acceptance criteria.

### 10.3 Pages

#### Library page (`/`)

- Dropzone + file picker (accept: `.mov,.mp4,.m4v,.heic,.heif,.jpg,.jpeg,.png`)
- List uploaded files in session
- Click row → navigate to `/editor/:fileId`

#### Editor page (`/editor/:fileId`)

Three columns (responsive collapse on narrow screens):

1. **Preview** — `<img>` from `/preview.jpg` or `<video>` + poster.
2. **Metadata** — monospace text from API.
3. **Layout map** — colored bar + segment list.

Interactions:

- Click segment → side panel with offset, size, category, edit safety, hex preview.
- Zoom slider for layout map (match desktop MIN/MAX bytes-per-pixel concept).

### 10.4 Agent tasks

#### M3-T1 — Scaffold `web/`

```bash
cd web && npm create vite@latest . -- --template react-ts
```

#### M3-T2 — API client (`web/src/api/client.ts`)

Typed functions mirroring M2 routes.

#### M3-T3 — Components

| Component | Responsibility |
|-----------|----------------|
| `LayoutMap.tsx` | Canvas bar, colors from API |
| `SegmentList.tsx` | Virtualized list if > 200 segments |
| `SegmentDetail.tsx` | Hex/text preview |
| `MetadataPanel.tsx` | Plain text |
| `PreviewPanel.tsx` | Image/video |

#### M3-T4 — Frontend tests

| Test | Tool | Checks |
|------|------|--------|
| `LayoutMap.test.tsx` | Vitest | renders N segments with correct widths |
| `api.client.test.ts` | Vitest | mocks fetch responses |
| `editor.spec.ts` | Playwright | upload fixture → sees metadata |

#### M3-T5 — Playwright E2E setup

`web/tests/editor.spec.ts`:

1. Start API (`uvicorn`) via Playwright `webServer` config.
2. Upload `video6.mov` through UI.
3. Assert metadata contains `video6.mov`.
4. Assert layout segment list non-empty.

### 10.5 Acceptance criteria (M3)

- [ ] `npm run build` succeeds.
- [ ] Vitest passes.
- [ ] Playwright E2E passes with API running.
- [ ] No transfer/convert buttons yet (read-only).

### 10.6 Agent verification command

```bash
.venv/bin/uvicorn api.main:app --port 8765 &
cd web && npm install && npm run test && npm run build
cd web && npx playwright test
```

---

## 11. Milestone M4 — Background jobs (transfer, convert, preview)

### 11.1 Objectives

Async processing for mutating operations with job polling and downloadable results.

### 11.2 Job model

```python
class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"

class JobRecord:
    id: str
    type: Literal["transfer", "convert", "update_preview"]
    status: JobStatus
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    input_file_ids: list[str]
    output_file_id: str | None
    params: dict
```

**M4 v1 implementation:** in-process background tasks (FastAPI `BackgroundTasks`) or threaded queue — **no Redis required for M4**. Add Redis in M6 if needed.

For CI/agent simplicity:

- `api/jobs.py` runs jobs synchronously when env `JOBS_SYNC=1` (test mode).
- Default: thread pool executor with max 2 workers.

### 11.3 Job types

#### Transfer

```
POST /api/v1/jobs/transfer
{
  "target_file_id": "...",
  "source_file_id": "...",
  "output_filename": "video6_with_metadata.mov"
}
```

Worker calls `core.transfer.transfer_metadata_files`.

Validate: same media kind (video/video or image/image).

#### Convert

```
POST /api/v1/jobs/convert
{
  "source_file_id": "...",
  "output_filename": "out.mp4",
  "target": "mp4"   // mp4 | mov | mkv | webm | jpeg | png | heic
}
```

Skip test if FFmpeg missing.

#### Update preview

```
POST /api/v1/jobs/update-preview
{
  "source_file_id": "...",
  "output_filename": "video6_preview_updated.mov"
}
```

Implementation: copy input to temp output → `core.preview.update_embedded_preview(output)` → register output file.

**Never mutate the uploaded original.**

### 11.4 Agent tasks

#### M4-T1 — Job storage

SQLite table `jobs` in `data/jobs.db` or JSON files in `data/jobs/`.

#### M4-T2 — Routes

| Method | Path |
|--------|------|
| `POST` | `/api/v1/jobs/transfer` |
| `POST` | `/api/v1/jobs/convert` |
| `POST` | `/api/v1/jobs/update-preview` |
| `GET` | `/api/v1/jobs/{job_id}` |
| `GET` | `/api/v1/files/{file_id}/download` |

#### M4-T3 — Integration tests

`tests/integration/test_api_jobs.py`:

| Test | Assertion |
|------|-----------|
| `test_transfer_video6` | output exists; moov/meta present; duration matches target |
| `test_transfer_heic` | output readable by `inspect_metadata` |
| `test_update_preview` | moov/meta contains `artwork` and JPEG magic |
| `test_convert_mp4` | skip if no ffmpeg; output is valid mp4 |
| `test_job_failure_bad_pair` | image target + video source → 400 |

Use `JOBS_SYNC=1` in pytest env.

### 11.5 Acceptance criteria (M4)

- [ ] All job integration tests pass.
- [ ] Original uploads unchanged after job.
- [ ] Failed jobs set `status=failed` with message.
- [ ] Download endpoint streams file with correct `Content-Disposition`.

### 11.6 Agent verification command

```bash
JOBS_SYNC=1 .venv/bin/pytest tests/integration/test_api_jobs.py -v
```

---

## 12. Milestone M5 — Web frontend (full parity)

### 12.1 Objectives

Add library transfer workflow, convert buttons, update preview, job progress UI.

### 12.2 UI features

| Desktop control | Web implementation |
|-----------------|-------------------|
| Transfer Metadata (library row) | Modal: pick source file from session → run job → download |
| Convert to MP4/MOV/... | Toolbar dropdown → job → download |
| Update Preview | Toolbar button → confirm dialog → job → download |
| Unknown Headers | Modal with API text field |
| Unknown Memory | Modal with API text field |

Add API helpers if missing:

```
GET /api/v1/files/{file_id}/unknown-headers
GET /api/v1/files/{file_id}/unknown-memory
```

### 12.3 Agent tasks

#### M5-T1 — Transfer modal component

#### M5-T2 — Job progress component

Poll `GET /jobs/{id}` every 1s until terminal state.

#### M5-T3 — Download handler

Trigger browser download from `/files/{id}/download`.

#### M5-T4 — E2E tests

| Spec file | Scenario |
|-----------|----------|
| `transfer.spec.ts` | video6 + video6_meta_source → download → re-upload → layout shows meta |
| `preview-update.spec.ts` | update preview → download → moov/meta size increases |
| `convert.spec.ts` | convert to mp4 (skip in CI if no ffmpeg) |

### 12.4 Acceptance criteria (M5)

- [ ] Full workflow reproducible via Playwright.
- [ ] Parity checklist (Section 12.5) all checked.
- [ ] Desktop GUI still works independently.

### 12.5 Parity checklist

- [ ] Upload multiple files to session
- [ ] Open editor for each supported extension
- [ ] Memory map colors match categories: header, metadata, payload, structure, padding, unknown
- [ ] Segment click shows edit safety tooltip data
- [ ] Transfer video metadata (atom graft)
- [ ] Transfer image metadata (EXIF)
- [ ] Convert video (≥ 1 format)
- [ ] Convert image (≥ 1 format)
- [ ] Update preview on video
- [ ] Download results without overwriting originals

---

## 13. Milestone M6 — Production hardening

### 13.1 Objectives

Deployable Docker stack, CI pipeline, file cleanup, limits.

### 13.2 Agent tasks

#### M6-T1 — Docker

`Dockerfile.api`:

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-api.txt
COPY . .
ENV UPLOAD_DIR=/data/uploads
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

`docker-compose.yml`:

- `api` service
- `web` service (nginx static)
- volume `uploads_data`

#### M6-T2 — CI (GitHub Actions)

`.github/workflows/ci.yml`:

```yaml
jobs:
  python:
    steps:
      - pip install -r requirements.txt -r requirements-dev.txt
      - pytest tests/ -v --ignore=tests/e2e
  web:
    steps:
      - npm ci && npm test && npm run build
  e2e:
    needs: [python, web]
    steps:
      - docker compose up -d
      - npx playwright test
```

#### M6-T3 — Upload limits

- `MAX_UPLOAD_BYTES` env (default 500_000_000).
- Return 413 when exceeded.

#### M6-T4 — TTL cleanup

`api/cleanup.py` — delete sessions older than `SESSION_TTL_HOURS` (default 24).

Cron or startup background sweep.

#### M6-T5 — Security headers + CORS

- CORS allow frontend origin only.
- No directory listing on uploads.

#### M6-T6 — README updates

Document: self-host, env vars, ffmpeg requirement, privacy/TTL.

### 13.3 Acceptance criteria (M6)

- [ ] `docker compose up` → web + API healthy.
- [ ] CI green on clean checkout (with OfmContent submodule or fixture download documented).
- [ ] Cleanup removes old sessions in test.

---

## 14. API specification

Base URL: `/api/v1`

### 14.1 Sessions

**POST `/sessions`**

Response 201:

```json
{ "session_id": "uuid" }
```

**POST `/sessions/{session_id}/files`**

`multipart/form-data`, field `file`.

Response 201:

```json
{
  "file_id": "uuid",
  "filename": "video6.mov",
  "size": 2658231,
  "media_kind": "video"
}
```

### 14.2 Inspect

**GET `/files/{file_id}/metadata`**

Response 200: `MetadataResult` (Section 15).

**GET `/files/{file_id}/layout`**

Response 200: `LayoutResult`.

**GET `/files/{file_id}/segments/{offset}?limit=512`**

Response 200:

```json
{
  "offset": 3419,
  "size": 512,
  "hex": "00 00 00 01 ...",
  "text": "...."
}
```

**GET `/files/{file_id}/preview.jpg`**

Response 200: `image/jpeg` body.

**GET `/files/{file_id}/unknown-headers`**

Response 200: `{ "text": "..." }`

**GET `/files/{file_id}/unknown-memory`**

Response 200: `{ "text": "..." }`

### 14.3 Jobs

**POST `/jobs/transfer`**

Request:

```json
{
  "target_file_id": "uuid",
  "source_file_id": "uuid",
  "output_filename": "output.mov"
}
```

Response 202: `{ "job_id": "uuid" }`

**GET `/jobs/{job_id}`**

Response 200: `JobResult`.

When `status == "succeeded"`, includes `output_file_id`.

**GET `/files/{file_id}/download`**

Response 200: binary stream, `Content-Disposition: attachment`.

### 14.4 Errors

Standard shape:

```json
{
  "error": "human_readable_message",
  "code": "transfer_failed"
}
```

| HTTP | When |
|------|------|
| 400 | Invalid job params, mismatched media kinds |
| 404 | Unknown session/file/job |
| 413 | Upload too large |
| 422 | Unsupported format |
| 500 | Unexpected worker failure |

---

## 15. Data transfer objects (DTOs)

Agent must implement these Pydantic models in `core/models.py` and use them in OpenAPI.

### 15.1 SegmentDTO

```python
class SegmentDTO(BaseModel):
    offset: int
    size: int
    end: int
    label: str
    category: Literal["header", "metadata", "payload", "structure", "padding", "unknown"]
    path: list[str]
    path_label: str
    edit_safety: EditSafetyDTO
```

### 15.2 EditSafetyDTO

```python
class EditSafetyDTO(BaseModel):
    level: Literal["safe", "caution", "unsafe"]
    label: str
    reason: str
    mark: str  # e.g. "✓", "!", "✗"
```

Populate via `layout.edit_safety.get_edit_safety`.

### 15.3 LayoutResult

```python
class LayoutResult(BaseModel):
    file_size: int
    segments: list[SegmentDTO]
    summary: dict[str, int]  # category -> count
```

### 15.4 MetadataResult

```python
class MetadataSection(BaseModel):
    title: str
    lines: list[str]

class MetadataResult(BaseModel):
    filename: str
    format_label: str
    file_size: int
    sections: list[MetadataSection]
    text: str  # full formatted text for CLI parity

    def as_text(self) -> str:
        return self.text
```

### 15.5 JobResult

```python
class JobResult(BaseModel):
    id: str
    type: str
    status: str
    error: str | None
    output_file_id: str | None
    created_at: str
    finished_at: str | None
```

---

## 16. Testing strategy

### 16.1 Test pyramid

```
        ┌─────────────┐
        │  E2E (few)  │  Playwright: full upload → job → download
        ├─────────────┤
        │ Integration │  httpx + FastAPI; core + real fixtures
        ├─────────────┤
        │  Unit (many)│  core logic, DTOs, CLI parity
        └─────────────┘
```

### 16.2 Coverage targets

| Area | Target | Measured by |
|------|--------|-------------|
| `core/` | ≥ 80% line coverage | pytest-cov |
| `api/routes/` | ≥ 70% | pytest-cov |
| `web/src/components/LayoutMap` | ≥ 70% | Vitest |
| E2E | 3 critical paths | Playwright |

Agent runs: `pytest --cov=core --cov=api --cov-report=term-missing`.

### 16.3 Fixture policy

1. **Prefer real files** from `OfmContent/` (see Appendix A).
2. **Synthetic fixtures** only in `tests/fixtures/generated/` for edge cases (empty file, truncated atom).
3. **Never commit** large generated outputs; create in `tmp_path` during tests.
4. Tests must not modify files under `OfmContent/` — always copy to `tmp_path` first.

### 16.4 Test matrix by format

| Format | Metadata | Layout | Transfer | Convert | Preview |
|--------|----------|--------|----------|---------|---------|
| `.mov` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `.mp4` | ✓ | ✓ | optional | ✓ | ✓ |
| `.heic` | ✓ | ✓ (mdat split) | ✓ | ✓ | N/A |
| `.jpg` | ✓ | ✓ | ✓ | ✓ | N/A |
| `.png` | ✓ | ✓ | ✓ | ✓ | N/A |

### 16.5 Regression tests (must not break)

Agent maintains `tests/unit/test_regressions.py` with cases derived from project history:

| Case | Assertion |
|------|-----------|
| HEIC mdat item split | layout contains `mdat item #N Exif` with category metadata |
| GPS EXIF read | no KeyError on `avatar_meta_data_source.HEIC` |
| video6 artwork graft | transferred file has moov/meta; preview update replaces JPEG |
| video1–5 no artwork | small meta without artwork unless updated |

### 16.6 CI environment variables

| Variable | Value in CI | Purpose |
|----------|-------------|---------|
| `JOBS_SYNC` | `1` | deterministic job tests |
| `UPLOAD_DIR` | `/tmp/cmc-uploads` | isolated storage |
| `SKIP_FFMPEG` | `1` if ffmpeg absent | skip convert tests |

Agent detects ffmpeg:

```python
import shutil
pytest.importorskip("shutil")
ffmpeg = shutil.which("ffmpeg")
```

### 16.7 Manual QA script (agent-automatable)

Save as `scripts/qa_web_flow.sh`:

1. Start API.
2. `curl` create session + upload video6.mov + video6_meta_source.mov.
3. POST transfer job with `JOBS_SYNC=1`.
4. Download output.
5. `python main.py inspect downloaded.mov` → assert meta section present.

Agent must be able to run this script without editing.

---

## 17. Agent execution protocol

### 17.1 Before starting any milestone

1. Read this document section for the milestone.
2. Run Appendix B verification for **previous** milestone.
3. Create a git branch `web/M{n}-short-name`.
4. List files to create/modify before coding.

### 17.2 During implementation

- One commit per task (M{n}-T{k}) when possible.
- Every new module gets a corresponding test file in the same PR.
- Do not import PyQt6 from `core/` or `api/`.
- Copy media to `tmp_path` before mutation tests.

### 17.3 Definition of done (per milestone)

```
[ ] All acceptance criteria checked
[ ] pytest passes
[ ] No new linter errors
[ ] Appendix B commands pass
[ ] This document updated if API/deviations occurred
```

### 17.4 Prompt template for agents

When invoking an agent on milestone M{n}:

```
Implement milestone M{n} from docs/WEB_MIGRATION_STRATEGY.md.

Rules:
- Follow task IDs M{n}-T* in order.
- Do not skip tests.
- Use OfmContent fixtures via tests/conftest.py.
- Do not modify OfmContent files in place.
- Run verification commands from Appendix B when done.

Report:
- Tasks completed
- Test output summary
- Deviations from doc (if any)
```

### 17.5 Parallelization hints

| Can run in parallel | Must be sequential |
|--------------------|--------------------|
| M1 unit tests + M2 route stubs | M1 before M2 |
| M3 UI components + M4 job backend | M2 before M3 and M4 |
| M6 Docker + M5 E2E tests | M4 before M5 transfer E2E |

---

## 18. Risk register

| ID | Risk | Impact | Mitigation | Test |
|----|------|--------|------------|------|
| R1 | Large uploads exhaust disk | High | MAX_UPLOAD_BYTES, TTL cleanup | integration test 413 |
| R2 | FFmpeg missing in CI | Medium | SKIP_FFMPEG, conditional skip | pytest skip marker |
| R3 | HEIC decode fails | Medium | pillow-heif in Docker | heic fixture test |
| R4 | Layout map slow for 50+ segments | Low | virtualize list, limit hex | perf test optional |
| R5 | Finder artwork differs web vs desktop | Low | document behavior | preview update test |
| R6 | Concurrent jobs corrupt files | High | one worker per session or file locks | stress test optional |
| R7 | Privacy concerns | High | TTL, README, self-host docs | cleanup unit test |

---

## 19. Out of scope for v1 web

- User authentication / OAuth
- Persistent cloud library (files always session-scoped)
- WASM in-browser FFmpeg
- Rewriting QuickTime parser in JS
- Real-time collaborative editing
- Direct in-place edit of user's local filesystem (browser cannot do this)

---

## 20. Appendix A — Fixture inventory

Paths relative to repo root (`ofm-tools/`).

| Key | Path | Used for |
|-----|------|----------|
| `video6_target` | `OfmContent/TikTok/Video/video6.mov` | Layout, convert, preview |
| `video6_source` | `OfmContent/TikTok/Video/video6_meta_source.mov` | Transfer metadata, artwork |
| `video6_output` | `OfmContent/TikTok/Video/video6_with_metadata.mov` | Regression |
| `video1–5_*` | `OfmContent/TikTok/Video/video{N}*` | Transfer without artwork |
| `heic_source` | `OfmContent/TikTok/avatar_meta_data_source.HEIC` | HEIC layout + GPS |
| `heic_output` | `OfmContent/TikTok/avatar_with_metadata.heic` | HEIC transfer regression |

Agent: if a path is missing, skip related tests with clear message; do not fail entire CI unless marked `required`.

---

## 21. Appendix B — Command reference

All commands assume repo root `content-meta-data-changer/`.

### Setup

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
```

### M0 verification

```bash
.venv/bin/pytest tests/unit/test_smoke_fixtures.py -v
```

### M1 verification

```bash
.venv/bin/pytest tests/unit/ -v
.venv/bin/python main.py inspect ../OfmContent/TikTok/Video/video6.mov | head -20
```

### M2 verification

```bash
.venv/bin/pytest tests/integration/test_api_readonly.py -v
.venv/bin/uvicorn api.main:app --port 8765
curl -s http://127.0.0.1:8765/api/v1/health
```

### M4 verification

```bash
JOBS_SYNC=1 .venv/bin/pytest tests/integration/test_api_jobs.py -v
```

### Full suite (pre-release)

```bash
.venv/bin/pytest tests/ -v --cov=core --cov=api
cd web && npm test && npm run build
cd web && npx playwright test
```

### Desktop smoke (must still work)

```bash
.venv/bin/python main.py --gui
```

---

## Document maintenance

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-08-04 | — | Initial strategy |

When an agent deviates from this document, it **must** update the relevant section and increment the version table.
