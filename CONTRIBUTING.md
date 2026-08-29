# Contributing

Thanks for considering a contribution. This is a small, local-first tool; the
bar for changes is "does it make the PDF easier to understand, without making
the code harder to follow".

## Table of contents

- [Ground rules](#ground-rules)
- [Development setup](#development-setup)
- [Everyday commands](#everyday-commands)
- [Project layout](#project-layout)
- [Architectural rules](#architectural-rules)
- [Adding an extractor](#adding-an-extractor)
- [Adding an endpoint](#adding-an-endpoint)
- [Working on the UI](#working-on-the-ui)
- [Tests](#tests)
- [Style](#style)
- [Commits and pull requests](#commits-and-pull-requests)
- [Reporting bugs](#reporting-bugs)
- [Licence of contributions](#licence-of-contributions)

## Ground rules

1. **The core stays web-free.** `pdf_scope/core/` must never import
   FastAPI, Starlette or anything else from the web layer. It takes a path in
   and returns JSON-serialisable data.
2. **No PDF logic in the web layer.** `pdf_scope/web/app.py` calls the
   core; it does not touch PyMuPDF.
3. **Be honest about gaps.** If PyMuPDF cannot expose something, say so in the
   output (`known_limitations`, an `error` field, a UI notice) rather than
   returning an empty result that looks like an answer.
4. **Everything stays local.** No network calls, no telemetry, no cloud
   services, no databases.
5. **Output must be JSON-serialisable.** Binary payloads go to the artifact
   directory and are referenced by file name.

## Development setup

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements-dev.txt
```

Python 3.10 or newer. PyMuPDF is pinned to an exact version in
`requirements.txt` and `pyproject.toml`; if you change it, update both, plus
the version numbers in `README.md`, `NOTICE.md` and `docs/`.
`tests/test_packaging.py` fails if those two files disagree, so the sync is
checked rather than remembered.

Optionally, `make hooks` installs the pre-commit hooks in
`.pre-commit-config.yaml`: the same Ruff checks CI runs, plus a few hygiene
checks, before each commit. CI is the authority either way.

## Everyday commands

```bash
.venv/bin/python -m pytest
```

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

```bash
.venv/bin/python -m pdf_scope --reload
```

A `Makefile` wraps the same commands: `make install`, `make test`, `make lint`,
`make format`, `make run`, `make clean`.

## Project layout

See [docs/architecture.md](docs/architecture.md) for the full picture. Short
version:

```
pdf_scope/core/   extraction: one module per concern, pure Python
pdf_scope/web/    FastAPI app, document registry, process pool, static UI
tests/                 pytest suite with generated fixture PDFs
docs/                  documentation set
```

## Architectural rules

| Rule | Why |
| --- | --- |
| One PyMuPDF `Document` per extraction call, closed in a `finally` | PyMuPDF documents must not be shared across processes or threads |
| All PDF work runs in the process pool | PyMuPDF states it does not support multi-threaded use, and extraction is CPU-bound |
| Artifacts are namespaced by document id | No cross-document bleed |
| Core raises only `PdfScopeError` subclasses | The web layer maps them to status codes without importing PyMuPDF |
| Every geometry value is documented as PyMuPDF space | Numbers are meaningless without a stated origin |

## Adding an extractor

Say you want to expose a new PDF feature:

1. Put the extraction in the module that owns that concern under
   `pdf_scope/core/` — or add a new module if it is genuinely new
   (`shadings.py`, say). Keep it a plain function taking a `pymupdf.Document`
   and/or `pymupdf.Page` and returning JSON-safe data.
2. Wrap PyMuPDF calls that can fail in `try`/`except` and return an `error`
   string in place of the missing section, so one broken feature never aborts
   a whole page.
3. Convert geometry with the helpers in `core/coordinates.py`; convert
   anything else with `core.schema.jsonable`.
4. Wire it into `analyze_page` (or `analyze_document`) under a new top-level
   key, and document that key in [docs/schema.md](docs/schema.md).
5. If PyMuPDF only partly exposes the feature, add an entry to
   `KNOWN_LIMITATIONS` in `core/document.py` describing what is missing.
6. Add a fixture and a test.
7. Surface it in the UI: a panel, an overlay kind, or a details row, with the
   usual view / copy / download actions.

## Adding an endpoint

1. Add a module-level function in `pdf_scope/web/tasks.py` taking only
   picklable arguments; it opens its own document and closes it.
2. Add the route in `pdf_scope/web/app.py`, `await pool.run(...)` on that
   task, and translate core errors into HTTP status codes with the existing
   helpers (`_require`, `_require_ready`, `_json`, `_text_response`).
3. Document it in [docs/api.md](docs/api.md), including status codes and an
   example.

## Working on the UI

The front end is one HTML file, one CSS file and one JS file, with no build
step. Run the server with `--reload` and hard-refresh the browser.

- Keep the render/overlay contract intact: overlay boxes are positioned as
  `(coordinate - page_rect_origin) * zoom`, and the raster `dpi` is chosen
  independently of the layout `zoom`.
- Every element the UI shows needs view, copy and download affordances. Where
  one is impossible (image clipboard in some browsers), say so in the UI and
  offer the nearest alternative.
- Escape everything that comes from a PDF before inserting it into HTML — use
  the existing `escapeHtml` helper. PDFs are untrusted input.

## Tests

- Fixtures are generated with PyMuPDF in `tests/conftest.py`; do not commit
  binary PDFs.
- New extraction code needs a test asserting concrete values (a bbox, a font
  name, a colour), not just "it returned something".
- If your change touches concurrency or artifact paths, extend
  `tests/test_concurrency.py`.
- Everything must pass before a pull request: `pytest`, `ruff check`,
  `ruff format --check`.

## Style

- Type hints on every function; `from __future__ import annotations` at the
  top of each module.
- Comments in short, professional English, explaining *why* rather than
  restating the code.
- Docstrings on modules and public functions.
- Line length 100, enforced by Ruff (`pyproject.toml`).
- No absolute local paths, no secrets, no personal data anywhere in the repo.

## Commits and pull requests

- One logical change per pull request.
- Conventional-style subjects are welcome (`feat:`, `fix:`, `docs:`,
  `refactor:`, `test:`, `chore:`) but not enforced. Keep the subject under
  ~72 characters.
- Describe what changed, why, and how you verified it. Screenshots help for UI
  changes.
- Update `CHANGELOG.md` under `Unreleased`, and the docs that your change
  makes stale.

## Reporting bugs

Open an issue with:

- what you did, what you expected, what happened;
- the output of `.venv/bin/python -c "import pymupdf; print(pymupdf.version)"`,
  your Python version and OS;
- a PDF that reproduces it, **only if you are free to share it** — never
  attach confidential documents. A generated reproduction is better; see
  `tests/conftest.py` for how the fixtures are built.

## Licence of contributions

By contributing you agree that your contribution is licensed under the MIT
licence of this repository (see [LICENSE](LICENSE)). Note that the project
depends on PyMuPDF, which is AGPL-3.0 or commercially licensed — see
[NOTICE.md](NOTICE.md).
