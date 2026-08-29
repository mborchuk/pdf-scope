"""Check every relative Markdown link in the repository, including anchors.

The documentation is heavily cross-linked, and a renamed heading breaks links
silently. This runs in CI and locally:

    python .github/scripts/check_links.py

Only relative links are checked; external URLs are not fetched, so the check
needs no network and cannot fail because someone else's site is down.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", ".venv", ".workspace", "node_modules", "__pycache__"}
LINK = re.compile(r"\[[^\]^]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
EXTERNAL = ("http://", "https://", "mailto:", "tel:")


def slug(heading: str) -> str:
    """Reproduce GitHub's heading anchor.

    Lower-cased, punctuation removed except hyphens and underscores, spaces
    turned into hyphens. Inline code markers and links are stripped first, so
    ``### `GET /x` (note)`` and ``### GET /x (note)`` give the same anchor.
    """
    text = heading.strip().lstrip("#").strip()
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links keep their label
    text = text.replace("`", "").lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", "-", text.strip())


def anchors(path: Path) -> set[str]:
    """Every anchor a Markdown file offers: its headings, plus explicit ids."""
    found: set[str] = set()
    fenced = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if line.startswith("#"):
            found.add(slug(line))
        for name in re.findall(r"<a\s+(?:id|name)=\"([^\"]+)\"", line):
            found.add(name)
    return found


def markdown_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not SKIP_DIRS.intersection(path.relative_to(ROOT).parts)
    )


def main() -> int:
    problems: list[str] = []
    files = markdown_files()
    for page in files:
        for target in LINK.findall(page.read_text(encoding="utf-8")):
            if target.startswith(EXTERNAL):
                continue
            where = page.relative_to(ROOT)
            file_part, _, anchor = target.partition("#")
            destination = page.parent if not file_part else (page.parent / file_part)
            destination = destination.resolve()
            if file_part and not destination.exists():
                problems.append(f"{where} -> {target}: no such file")
                continue
            if not anchor or destination.suffix != ".md":
                continue
            if anchor not in anchors(destination):
                problems.append(f"{where} -> {target}: no such heading")

    for problem in problems:
        print(problem)
    print(f"checked {len(files)} Markdown files, {len(problems)} broken relative links")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
