# Third-party notices

The PDF decompiler source in this repository is released under the MIT licence
(see [LICENSE](LICENSE)). It depends on third-party packages that carry their
own licences. The most important one is **PyMuPDF**, which is **not**
permissively licensed.

## PyMuPDF / MuPDF — read this before redistributing

| | |
| --- | --- |
| Package | `pymupdf==1.28.2` (bundles MuPDF 1.28.2) |
| Vendor | Artifex Software, Inc. |
| Licence | Dual licensed: **GNU AGPL v3** *or* an Artifex commercial licence |
| Upstream | <https://github.com/pymupdf/pymupdf>, <https://artifex.com> |

What this means in practice:

- Running this application locally for your own use is unaffected.
- If you **distribute** a combined work that includes PyMuPDF, or **offer it to
  users over a network** (for example by hosting this UI as a service), the
  AGPL's terms apply to that combined work unless you hold an Artifex
  commercial licence. In practice that means the complete corresponding source
  of what you deploy must be offered to its users.
- The MIT licence on this repository covers **this repository's own code
  only**. It does not, and cannot, relicense PyMuPDF or MuPDF.

This is a description of the upstream licence terms, not legal advice. If you
plan to ship or host this application, check the terms yourself or talk to
Artifex about a commercial licence.

## Runtime dependencies

| Package | Version | Licence |
| --- | --- | --- |
| pymupdf | 1.28.2 | AGPL-3.0 or Artifex commercial |
| fastapi | 0.121.2 | MIT |
| starlette (via fastapi) | 0.49.3 | BSD-3-Clause |
| pydantic (via fastapi) | 2.13.5 | MIT |
| pydantic-core (via pydantic) | 2.46.5 | MIT |
| annotated-types (via pydantic) | 0.8.0 | MIT |
| typing-extensions | 4.16.0 | PSF-2.0 |
| anyio (via starlette) | 4.14.2 | MIT |
| idna (via anyio) | 3.19 | BSD-3-Clause |
| sniffio (via anyio) | 1.3.1 | MIT or Apache-2.0 |
| uvicorn | 0.41.0 | BSD-3-Clause |
| click (via uvicorn) | 8.5.0 | BSD-3-Clause |
| h11 (via uvicorn) | 0.16.0 | MIT |
| python-multipart | 0.0.20 | Apache-2.0 |

## Development dependencies

| Package | Version | Licence |
| --- | --- | --- |
| pytest | 8.4.2 | MIT |
| ruff | 0.14.4 | MIT |

## Assets

The user interface ships no third-party fonts, icons, images or JavaScript
libraries. `pdf_decompiler/web/static/` contains only hand-written HTML, CSS
and JavaScript from this repository, and the pages it renders come from the
user's own files.
