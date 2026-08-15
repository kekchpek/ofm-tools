# ofm-tools

Tooling for preparing social media content.

## Projects

### [content-meta-data-changer](content-meta-data-changer/)

Inspect, visualize, transfer, and update metadata for video and image files
(MOV/MP4, HEIC/HEIF, JPEG, PNG).

Beyond reading and writing metadata, it maps a file's **byte-level memory
layout**: every QuickTime atom, JPEG marker, and PNG chunk is shown as a byte
range, classified (header / metadata / payload / structure / padding / unknown),
and annotated with an edit-safety verdict so you can see what is safe to touch
before changing anything.

It ships as four frontends over one shared core:

| Surface | Entry point |
|---------|-------------|
| Web app (React + FastAPI) | `./start_server` |
| Desktop app (PyQt) | `python main.py --gui` |
| CLI | `python main.py inspect <file>` |
| HTTP API | `uvicorn api.main:app` |

See [content-meta-data-changer/README.md](content-meta-data-changer/README.md)
for setup, environment variables, and deployment.

## Sample media

`OfmContent/` holds sample Instagram and TikTok media used as test fixtures. It
is deliberately **not** version controlled — it is large and consists of real
content. Tests that need it skip automatically when it is absent, so the suite
still runs on a fresh clone and in CI.

To point the tests at fixtures kept elsewhere:

```bash
OFM_CONTENT_DIR=/path/to/fixtures pytest content-meta-data-changer/tests/
```

## CI

[.github/workflows](.github/workflows/) runs the Python test suite and a
frontend production build on every push and pull request.
