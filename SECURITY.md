# Security policy

## Threat model in one paragraph

PDF decompiler is a **local, single-user tool**. It binds to `127.0.0.1` by
default, has no authentication, no accounts and no database, and it never sends
anything anywhere. Its input — PDF files — is untrusted by nature: a PDF can
carry JavaScript, embedded files, malformed streams and deliberately hostile
structures. The application parses those files with PyMuPDF/MuPDF and shows
what it finds; it never executes PDF JavaScript, never opens embedded files,
and never follows links on your behalf.

## What the application does with your files

| | |
| --- | --- |
| Where uploads go | `<workspace>/<document_id>/source.pdf`, workspace defaults to `./.workspace` |
| Other artifacts | Extracted images, cached page reports and export bundles in the same per-document directory |
| Lifetime | Deleted when you close the document; the whole workspace is emptied when the server starts |
| Network | None. No outbound requests, no telemetry, no update checks |
| Logging | Uvicorn's request log on stdout; document ids appear in URLs, file contents do not |

## Safe operation

- **Keep it on localhost.** The default bind is `127.0.0.1`. Passing
  `--host 0.0.0.0` exposes an unauthenticated file-upload and file-download
  service to your network. Do not do that on an untrusted network, and do not
  put it on the public internet without an authenticating reverse proxy.
- **Treat the workspace as sensitive.** It holds copies of every PDF you
  opened plus everything extracted from them. Point
  `PDF_DECOMPILER_WORKSPACE` at a location with appropriate permissions if the
  default working directory is shared.
- **Passwords for encrypted PDFs** are held in memory for the lifetime of the
  document entry so page extraction can reopen the file. They are never
  written to disk and never included in any report or export.
- **Rendered pages and extracted content come from untrusted files.** The UI
  escapes PDF-derived text before inserting it into the DOM, renders pages as
  raster PNGs rather than executing anything, and shows JavaScript found in a
  document as inert text.

## Known, accepted limitations

These are design consequences of a local tool, not bugs:

- No authentication or authorisation on the HTTP API.
- No rate limiting beyond the worker-pool cap and the upload size limit.
- No sandboxing of MuPDF: a parser vulnerability in a malicious PDF would run
  with the privileges of the server process. Keep PyMuPDF up to date and do not
  point this tool at files you would not open in any other reader.
- Document ids are unguessable UUIDs, but anyone who can reach the port can
  list every open document via `GET /api/documents`.

## Reporting a vulnerability

Report privately, not in a public issue:

- Preferred: GitHub → the repository's **Security → Report a vulnerability**
  form (private advisory).
- Alternative: open a public issue that says only "security report, please
  make contact" with no details, and wait for a private channel.

Please include what you found, how to reproduce it, and the impact you see.
A generated proof-of-concept PDF is far better than a real document; never
attach confidential files.

This is a spare-time project: expect an acknowledgement within about a week.
Fixes ship in a normal release, credited in `CHANGELOG.md` unless you prefer
otherwise.

## Supported versions

The most recent release on `main` is the only supported version.

## Upstream security

Most parsing risk lives in PyMuPDF/MuPDF rather than in this repository. Report
issues in the parser to the upstream project at
<https://github.com/pymupdf/pymupdf/security>, and keep the pinned version
current.
