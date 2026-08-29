# Development

Working on the code: environment, code map, tests, common tasks, release.
Contribution etiquette lives in [CONTRIBUTING.md](../CONTRIBUTING.md); this
page is the technical companion.

- [Environment](#environment)
- [Commands](#commands)
- [Code map](#code-map)
- [Invariants to preserve](#invariants-to-preserve)
- [Tests](#tests)
- [Writing fixtures](#writing-fixtures)
- [Common tasks](#common-tasks)
- [Verifying against PyMuPDF](#verifying-against-pymupdf)
- [Debugging](#debugging)
- [Continuous integration](#continuous-integration)
- [Release process](#release-process)

## Environment

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
```

Python 3.10+. All dependencies are pinned to exact versions; `pyproject.toml`
and `requirements.txt` must stay in sync.

Editor settings come from `.editorconfig`. Ruff config (line length 100, rule
selection) lives in `pyproject.toml`.

## Commands

| Task | Command | `make` |
| --- | --- | --- |
| Run the server | `.venv/bin/python -m pdf_scope` | `make run` |
| Run with reload | `.venv/bin/python -m pdf_scope --reload` | `make dev` |
| Tests | `.venv/bin/python -m pytest` | `make test` |
| One test | `.venv/bin/python -m pytest tests/test_page.py::test_images_placements_and_files -q` | — |
| Lint | `.venv/bin/ruff check .` | `make lint` |
| Format | `.venv/bin/ruff format .` | `make format` |
| Lint + tests | — | `make check` |
| Remove caches and workspace | — | `make clean` |
| End-to-end smoke test | `python .github/scripts/smoke_test.py http://127.0.0.1:8000` | — |

## Code map

| File | Responsibility | Touch it when |
| --- | --- | --- |
| `core/document.py` | Opening, authentication, document report, permissions, fonts, forms, attachments, outline, `KNOWN_LIMITATIONS` | Adding document-level information |
| `core/page.py` | Assembling the page report, content-stream section | Adding a page-level section |
| `core/objects.py` | xref access, dictionary parsing, page tree, name trees, structure tree, page resources | Anything about the object model |
| `core/contentstream.py` | The PDF content-stream lexer | Operator parsing, inline images, new operator descriptions |
| `core/text.py` | Text granularities, flags, colours | Text extraction detail |
| `core/images.py` | Image bytes, properties, placements, dedup, inline images | Image handling |
| `core/drawings.py` | Vector paths | Path or colour handling |
| `core/annotations.py` | Annotations, links, widgets | Annotation detail |
| `core/render.py` | Page → PNG plus scale information | Rendering options |
| `core/export.py` | Zip bundles, whole-document text, combined JSON | Export layout |
| `core/coordinates.py` | Conventions and conversions | Anything geometric |
| `core/schema.py` | `SCHEMA_VERSION`, limits, `jsonable`, `dumps` | Serialisation, limits |
| `core/errors.py` | Exception hierarchy | New failure modes |
| `web/app.py` | Routes, error mapping, downloads | New endpoints |
| `web/registry.py` | Identity, artifact directories, lifecycle | Document management |
| `web/jobs.py` | Process pool and concurrency cap | Scheduling |
| `web/tasks.py` | Picklable worker entry points | Any new pool operation |
| `web/static/app.js` | The whole UI | Any interface change |

## Invariants to preserve

Break any of these and the project stops being what it claims to be:

1. `pdf_scope.core` imports nothing from `pdf_scope.web` and nothing
   web-related at all.
2. `web/app.py` never imports `pymupdf`.
3. Every core entry point opens its own `Document` and closes it in `finally`.
4. Only picklable values cross the process boundary.
5. Every report value is JSON-native; binary payloads go to disk.
6. Every coordinate is in PyMuPDF space, and every report says so.
7. A failure in one section becomes an `error` field, not an exception that
   loses the whole report.
8. Anything PyMuPDF cannot expose is reported, never silently dropped.
9. Artifacts are namespaced by document id.
10. PDF-derived strings are HTML-escaped before they reach the DOM.

A quick check for the first two:

```bash
grep -rn "fastapi\|starlette\|uvicorn" pdf_scope/core/ ; echo "expect no matches"
grep -n "pymupdf" pdf_scope/web/app.py ; echo "expect no matches"
```

## Tests

29 tests, all offline, no server needed, run in well under a second.

| File | Covers |
| --- | --- |
| `tests/conftest.py` | Fixture PDFs, generated with PyMuPDF |
| `tests/test_document.py` | Document report, metadata, fonts, outline, attachments, forms, structure sections, encryption, corrupt files |
| `tests/test_page.py` | Text granularities and font details, images and files on disk, drawings, annotations/links/widgets, content-stream operators, resources, coordinate conversion, rotated pages, scanned pages |
| `tests/test_objects.py` | Object descriptions, stream sizes, xref scan, page tree, reference helpers, dictionary-source parser, content-stream parser including inline images and limits |
| `tests/test_concurrency.py` | Two documents in a real process pool, artifact namespacing, export bundle contents, document text formats |

Assertions are concrete: exact bounding boxes, exact colours, exact font names.
That is deliberate — "returned something" would not catch a regression in
MuPDF's output.

## Writing fixtures

No binary PDFs in the repository. Fixtures are built with PyMuPDF in
`tests/conftest.py`:

```python
@pytest.fixture(scope="session")
def my_pdf(tmp_path_factory):
    path = tmp_path_factory.mktemp("fixtures") / "my.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=400, height=500)
    page.insert_text((72, 100), "hello", fontname="helv", fontsize=14)
    doc.save(path)
    doc.close()
    return path
```

`png_bytes()` in the same file builds a solid-colour PNG without extra
dependencies, for image fixtures. Existing fixtures: `rich_pdf`,
`rotated_pdf`, `scanned_pdf`, `encrypted_pdf`, `corrupt_pdf`, `second_pdf`.

## Common tasks

**Add a field to the page report**

1. Extract it in the owning `core/` module, failing soft.
2. Add it under a clear key in `core/page.py`.
3. Document it in `docs/schema.md`.
4. Assert it in `tests/test_page.py`.
5. Show it in the UI.

**Add an endpoint**

1. `web/tasks.py`: a module-level function with picklable arguments.
2. `web/app.py`: a route that `await pool.run(...)`s it and maps errors.
3. `docs/api.md`: parameters, status codes, an example.

**Add an operator description**

Extend `OPERATOR_DESCRIPTIONS` in `core/contentstream.py`. Keep descriptions
short and lower-case; they are rendered in a table column.

**Change a limit**

Constants live in `core/schema.py`, `core/objects.py`, `core/document.py`,
`core/render.py` and `web/registry.py`. Update the tables in
`docs/schema.md#truncation-and-limits` and
`docs/configuration.md#built-in-limits`.

**Bump PyMuPDF**

Change the pin in `requirements.txt` **and** `pyproject.toml`, update the
version strings in `README.md`, `NOTICE.md` and `docs/`, then run the tests.
Expect text block segmentation, image DPI reporting or drawing decomposition to
shift slightly between MuPDF releases; if a test fails, decide whether the new
behaviour is correct before changing the assertion.

## Verifying against PyMuPDF

The API has changed across versions, so check the real thing rather than
memory:

```bash
.venv/bin/python -c "import pymupdf; print(pymupdf.version, pymupdf.mupdf_version)"
.venv/bin/python -c "import pymupdf, inspect; print(inspect.signature(pymupdf.Page.get_image_info))"
.venv/bin/python -c "import pymupdf; print([m for m in dir(pymupdf.Document) if 'xref' in m])"
```

Upstream documentation: <https://pymupdf.readthedocs.io/en/latest/>. Notable
details this project relies on:

- `Document.is_encrypted` means *still locked* and flips to `False` after
  `authenticate()`; the report derives real encryption from `needs_pass` plus
  the metadata method string.
- There is no `Document.is_linearized`; the flag is `is_fast_webaccess`.
- `Page.get_image_info(hashes=..., xrefs=True)` is what associates placements
  with image xrefs.
- `Page.get_text("blocks")` returns tuples, not dicts.
- PyMuPDF states it does not support multi-threaded use.

## Debugging

**Server-side**: run with `--reload` and add `print()`/`logging` in the web
layer. Code inside a worker process cannot write to the terminal reliably —
easier to call the core function directly in a script.

**Extraction**: reproduce without the server.

```python
from pdf_scope.core import analyze_page, dumps
print(dumps(analyze_page("suspect.pdf", 0))[:4000])
```

**Front-end**: the browser console; there is no build step or source map to
worry about. `state` is module-scoped, so add a temporary
`window.state = state` while debugging.

**Process pool**: set `PDF_SCOPE_WORKERS=1` to serialise work and make
tracebacks easier to read.

## Continuous integration

`.github/workflows/ci.yml` runs on push and pull request:

| Job | What it does |
| --- | --- |
| `lint` | `ruff check` and `ruff format --check` |
| `test` | `pytest` on Python 3.10–3.14 on Linux, plus 3.12 on macOS and Windows |
| `smoke` | Starts the server, uploads a generated PDF, checks the report, render and export, then closes the document |

`.github/dependabot.yml` proposes monthly updates for pip and GitHub Actions.

## Release process

1. Everything green: `make check`, plus the smoke test against a running
   server.
2. Update `CHANGELOG.md`: move `Unreleased` items under a new version heading
   with the date.
3. Bump the version in `pyproject.toml` and `pdf_scope/__init__.py`.
4. If the report shape changed incompatibly, bump `SCHEMA_VERSION` in
   `core/schema.py` and say so in the changelog.
5. Refresh version strings in `README.md`, `NOTICE.md` and `docs/README.md`.
6. Tag `vX.Y.Z` and push the tag; create a GitHub release using the changelog
   section as its body.

Versioning: [SemVer](https://semver.org/) for the application, with
`schema_version` tracked separately as described in
[schema.md](schema.md#versioning).
