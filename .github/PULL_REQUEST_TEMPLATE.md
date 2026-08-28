## What this changes

<!-- One or two sentences. Link the issue it closes, if any. -->

## Why

<!-- The problem being solved, or the PDF feature being exposed. -->

## How it was verified

<!-- Commands run, documents tested against, screenshots for UI changes. -->

```
pytest:
ruff check:
ruff format --check:
```

## Checklist

- [ ] `pytest` passes
- [ ] `ruff check .` and `ruff format --check .` pass
- [ ] The extraction core still imports nothing from the web layer
- [ ] New or changed output keys are documented in `docs/schema.md`
- [ ] New or changed endpoints are documented in `docs/api.md`
- [ ] Anything PyMuPDF cannot expose is stated in the output, not silently omitted
- [ ] `CHANGELOG.md` updated under `Unreleased`
- [ ] No confidential documents, personal data or absolute local paths added
