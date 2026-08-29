# Configuration and operations

- [Command line](#command-line)
- [Environment variables](#environment-variables)
- [Built-in limits](#built-in-limits)
- [Where data lives](#where-data-lives)
- [Performance](#performance)
- [Resource sizing](#resource-sizing)
- [Running behind a reverse proxy](#running-behind-a-reverse-proxy)
- [Running with Docker](#running-with-docker)
- [Running as a service](#running-as-a-service)
- [Health checks and monitoring](#health-checks-and-monitoring)
- [Logging](#logging)
- [Upgrading](#upgrading)

## Command line

```bash
.venv/bin/python -m pdf_decompiler [--host HOST] [--port PORT] [--reload]
```

| Option | Default | Notes |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Anything else exposes an unauthenticated service — read [SECURITY.md](../SECURITY.md) first |
| `--port` | `8000` | |
| `--reload` | off | Uvicorn auto-reload; development only, and it restarts the process pool on every change |

To run uvicorn yourself (extra workers are **not** appropriate here — see
[Performance](#performance)):

```bash
.venv/bin/uvicorn pdf_decompiler.web.app:app --host 127.0.0.1 --port 8000
```

## Environment variables

| Variable | Default | Effect |
| --- | --- | --- |
| `PDF_DECOMPILER_WORKSPACE` | `<cwd>/.workspace` | Directory for per-document artifacts. Expanded and resolved at startup. **Emptied on every start** |
| `PDF_DECOMPILER_WORKERS` | `min(4, os.cpu_count())` | Worker processes, and therefore the maximum number of simultaneous extractions |
| `PDF_DECOMPILER_MAX_UPLOAD_MB` | `512` | Per-file upload ceiling; larger files are rejected with a message |

Example:

```bash
PDF_DECOMPILER_WORKSPACE=/var/tmp/pdfd \
PDF_DECOMPILER_WORKERS=8 \
PDF_DECOMPILER_MAX_UPLOAD_MB=1024 \
.venv/bin/python -m pdf_decompiler --port 8080
```

Because the workspace is wiped at startup, never point it at a directory that
holds anything else.

## Built-in limits

Not environment-configurable; change the constant and restart if you need
something different.

| Limit | Value | Constant |
| --- | --- | --- |
| Open documents | 25 | `web.registry.MAX_OPEN_DOCUMENTS` |
| Objects scanned for the type histogram | 200 000 | `core.schema.XREF_SCAN_LIMIT` |
| Vector paths inlined per page report | 5 000 | `core.schema.PAGE_DRAWING_LIMIT` |
| Vector paths above which table detection is skipped | 20 000 | `core.tables.TABLE_DETECTION_PATH_GUARD` |
| Table rows / Markdown kept per table | 300 rows, 40 000 chars | `core.tables.TABLE_ROW_LIMIT`, `TABLE_MARKDOWN_LIMIT` |
| Pages counted per summary request | 25 (max 200) | `limit` on `/summary` |
| Operators inlined per page report | 5 000 | `core.schema.PAGE_OPERATOR_LIMIT` |
| Nodes per structure/name-tree walk | 5 000 | `core.objects.DEFAULT_NODE_LIMIT` |
| Inlined decoded content stream | 200 000 chars | `core.schema.CONTENT_STREAM_INLINE_LIMIT` |
| Operators per window request | 20 000 | `core.schema.CONTENT_STREAM_OPERATOR_LIMIT` |
| Pages scanned for the font list | 2 000 | `core.document.FONT_SCAN_PAGE_LIMIT` |
| Render resolution | 24–400 dpi | `core.render.MAX_DPI` |

Every one of these reports when it is hit — see
[schema.md](schema.md#truncation-and-limits). Raising them costs memory and
response size, not correctness.

## Where data lives

| Path | Content | Lifetime |
| --- | --- | --- |
| `<workspace>/<id>/source.pdf` | Verbatim copy of the upload | Until the document is closed or the server restarts |
| `<workspace>/<id>/images/` | Extracted images | Same |
| `<workspace>/<id>/cache/` | Page reports as JSON | Same |
| `<workspace>/<id>/exports/` | Built zip bundles | Same |
| Memory | Document reports, statuses, passwords for unlocked documents | Process lifetime |

Nothing else is written anywhere. No temporary directory outside the
workspace, no user config file, no cache in `$HOME`.

## Performance

Measured on an Apple M-series laptop with four workers, PyMuPDF 1.28.2:

| Operation | Typical cost |
| --- | --- |
| Document analysis, 4-page file | ~30 ms |
| Document analysis, 300-page text file | ~0.7 s |
| Page report, text page with an image | 20–60 ms |
| Page report, served from the disk cache | ~2 ms |
| Page render at 96 dpi, A4 | 20–50 ms |
| Complete export bundle, 4-page file | ~0.3 s |

What dominates:

- **Document analysis** scales with the number of objects (the xref scan) and
  the number of pages (font aggregation, page summaries, form fields). It never
  touches page content, which is why it stays sub-second on large files.
- **Page reports** scale with the amount of content on the page: character
  count, number of paths, number of images. A page with 20 000 vector paths is
  the usual worst case.
- **Exports** re-extract every page, so they cost roughly `pages × page report`
  plus zip compression.
- **Renders** scale with `dpi²`.

Tuning:

- Raise `PDF_DECOMPILER_WORKERS` on a many-core machine when several documents
  are analysed at once. It does not speed up a single page.
- Lower the zoom in the UI to render fewer pixels.
- Turn off the *Characters* overlay on text-heavy pages; it is the only overlay
  that can create tens of thousands of DOM nodes.
- Scrolling a long document costs one render plus one page report per page that
  comes into view; both are cheap and the page report is served from the disk
  cache the second time. Only pages near the viewport are ever loaded, so page
  count itself does not cost anything.
- Do **not** run uvicorn with `--workers N`: each OS worker would get its own
  in-memory registry, so documents would appear and disappear depending on
  which worker answered. Scale with `PDF_DECOMPILER_WORKERS` instead.

## Resource sizing

| Resource | Rule of thumb |
| --- | --- |
| Disk | Source file + extracted images + page cache. Page cache is roughly 5–50 KB per page of JSON; image-heavy documents dominate |
| Memory, main process | Base ~120 MB, plus one document report per open document (tens of KB to a few MB) |
| Memory, per worker | Base ~80 MB, plus MuPDF's working set for the file being processed. A large scanned page can briefly need a few hundred MB while rendering |
| CPU | One core saturated per active worker |

With 25 documents open and four workers, expect a few hundred MB of RSS in
total and disk usage proportional to what you actually browse.

## Running behind a reverse proxy

The app has no authentication. If it must be reachable beyond localhost, put an
authenticating proxy in front and keep the app bound to loopback:

```nginx
server {
    listen 443 ssl;
    server_name pdf.internal.example;

    auth_basic           "pdf decompiler";
    auth_basic_user_file /etc/nginx/htpasswd;

    client_max_body_size 512m;          # match PDF_DECOMPILER_MAX_UPLOAD_MB

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_read_timeout 600s;        # complete exports can take minutes
        proxy_buffering    off;         # stream large downloads
    }
}
```

Points to get right: a body-size limit at least as large as the app's upload
limit, a generous read timeout for exports, and buffering off so large zips
stream. Remember that hosting the app for other users has AGPL implications
through PyMuPDF — see [NOTICE.md](../NOTICE.md).

## Running with Docker

No image is published; a minimal one is three lines:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY pdf_decompiler ./pdf_decompiler
ENV PDF_DECOMPILER_WORKSPACE=/data
VOLUME /data
EXPOSE 8000
CMD ["python", "-m", "pdf_decompiler", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -t pdf-decompiler .
docker run --rm -p 127.0.0.1:8000:8000 pdf-decompiler
```

Publish the port to `127.0.0.1` only, unless you have added authentication.
`--host 0.0.0.0` inside the container is required for the port mapping to
work; it is the published address that matters.

## Running as a service

systemd user unit, for a machine where you want it always available locally:

```ini
[Unit]
Description=PDF decompiler
After=network.target

[Service]
WorkingDirectory=%h/pdf-decompiler
Environment=PDF_DECOMPILER_WORKSPACE=%h/.cache/pdf-decompiler
ExecStart=%h/pdf-decompiler/.venv/bin/python -m pdf_decompiler --port 8000
Restart=on-failure

[Install]
WantedBy=default.target
```

Every restart empties the workspace, which is the intended behaviour.

## Health checks and monitoring

`GET /api/status` answers as soon as the app is up and reports the pool state:

```bash
curl -sf http://127.0.0.1:8000/api/status
```

```json
{"schema_version":"1.0","documents_open":2,"max_documents":25,
 "workspace":"/var/tmp/pdfd","pool":{"workers":4,"running":1,"started":true}}
```

`pool.running` is the number of extractions in flight — a simple saturation
signal. There are no metrics endpoints, no tracing and no telemetry.

## Logging

Uvicorn's default access and error logs go to stdout. Request paths contain
document ids; file names and document content never appear in the log. To
quieten it, run uvicorn directly with `--log-level warning`.

## Upgrading

1. Read [CHANGELOG.md](../CHANGELOG.md), especially any `schema_version` bump.
2. Pull, then reinstall the pinned dependencies:

```bash
.venv/bin/pip install -r requirements.txt
```

3. Restart. The workspace is emptied automatically, so no manual cleanup is
   needed, and no state migration exists to worry about.

Changing the PyMuPDF pin is a deliberate act: extraction output can shift
between MuPDF versions (text block segmentation and image DPI reporting are the
usual candidates). Run the test suite after any such change.
