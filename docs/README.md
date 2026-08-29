# PDF Scope documentation

Everything about the project, in reading order. Start at
[Getting started](getting-started.md) if you just want it running.

## The documents

| Document | What it covers |
| --- | --- |
| [Getting started](getting-started.md) | Install, run, first document, a five-minute tour of the UI |
| [Concepts: how a PDF is built](pdf-primer.md) | Objects, xrefs, page tree, resources, content streams, coordinate systems — the vocabulary the rest of the docs use |
| [Architecture](architecture.md) | Process model, module map, request flows, design decisions and their trade-offs |
| [User interface guide](ui-guide.md) | Every panel, every overlay, every view/copy/download action |
| [HTTP API reference](api.md) | All endpoints with parameters, status codes, headers and examples |
| [Extraction schema reference](schema.md) | Every field of the document and page reports, field by field |
| [Core Python API](core-api.md) | Using `pdf_scope.core` without the web layer |
| [Coverage: what is and is not extracted](coverage.md) | Mapping to PDF features, and everything PyMuPDF cannot reach |
| [Multi-document behaviour](multi-document.md) | Identity, isolation, concurrency, lifecycle, artifact layout |
| [Configuration and operations](configuration.md) | Environment variables, limits, performance, resource use, running behind a proxy |
| [Troubleshooting](troubleshooting.md) | Symptoms, causes, fixes |
| [Development](development.md) | Code map, tests, adding features, release process |
| [Repository configuration](repository.md) | GitHub settings, CI and automation, plan limits, the checklist for going public |

## Repository documents

| Document | What it covers |
| --- | --- |
| [README](../README.md) | Project overview and quick reference |
| [CHANGELOG](../CHANGELOG.md) | Release history |
| [CONTRIBUTING](../CONTRIBUTING.md) | How to work on the project |
| [SECURITY](../SECURITY.md) | Threat model, safe operation, reporting |
| [NOTICE](../NOTICE.md) | Third-party licences, including PyMuPDF's AGPL terms |
| [CODE_OF_CONDUCT](../CODE_OF_CONDUCT.md) | Behaviour expected in project spaces |
| [Dockerfile](../Dockerfile) | Container image; usage in [configuration.md](configuration.md#running-with-docker) |

## Conventions used throughout

- **PyMuPDF space** — every coordinate in this project is in PDF points
  (1/72 inch) with the origin at the **top-left** of `page.rect` and y growing
  **downwards**. The PDF file format itself uses a bottom-left origin. See
  [Coordinate systems](pdf-primer.md#coordinate-systems).
- **Page numbers** — zero-based everywhere in the API and in JSON
  (`page_number: 0` is the first page). The UI and file names in export
  bundles are one-based (`Page 1`, `page-0001.json`).
- **xref** — a PDF object number. Object 0 is always the free-list head, so
  usable xrefs run from 1 to `xref_length - 1`.
- **Document id** — a 32-character hex UUID assigned by the server per open
  document, unrelated to the PDF's own `/ID`.
- Shell examples assume a virtual environment at `.venv`.

## Version

This documentation describes **PDF Scope 0.1.0**, extraction schema
version **1.0**, pinned to **PyMuPDF 1.28.2** (MuPDF 1.28.2).
