"""Packaging metadata must agree with the requirements files.

`requirements.txt` is what a user installs and what the container image builds
from; `pyproject.toml` is what a wheel declares. The documentation states they
are kept in sync, and a drift between them means one of the two install paths
gets untested versions. These tests are the enforcement.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

tomllib = pytest.importorskip("tomllib", reason="tomllib exists from Python 3.11")

ROOT = Path(__file__).resolve().parents[1]


def normalise(name: str) -> str:
    """Normalise a distribution name the way PEP 503 does."""
    return re.sub(r"[-_.]+", "-", name).lower()


def pinned(requirement: str) -> tuple[str, str]:
    """Split `name==version` into its normalised name and its version."""
    name, _, version = requirement.partition("==")
    assert version, f"{requirement!r} is not pinned with =="
    return normalise(name.strip()), version.strip()


def read_requirements(path: Path) -> dict[str, str]:
    """Read a requirements file into {name: version}, ignoring includes."""
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        name, version = pinned(line)
        pins[name] = version
    return pins


@pytest.fixture(scope="module")
def project() -> dict:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]


def test_runtime_pins_match_pyproject(project: dict) -> None:
    """Every [project.dependencies] pin appears in requirements.txt, same version.

    A requirements file may hold *more* than the project declares — pinning a
    transitive dependency for reproducibility is legitimate — but never a
    different version of the same package.
    """
    declared = dict(pinned(item) for item in project["dependencies"])
    from_file = read_requirements(ROOT / "requirements.txt")
    assert declared.keys() <= from_file.keys(), "declared but not in requirements.txt"
    assert {name: from_file[name] for name in declared} == declared


def test_dev_pins_match_pyproject(project: dict) -> None:
    """The `dev` extra and requirements-dev.txt agree on the tools they share."""
    declared = dict(pinned(item) for item in project["optional-dependencies"]["dev"])
    from_file = read_requirements(ROOT / "requirements-dev.txt")
    assert declared.keys() <= from_file.keys(), "declared in the dev extra but not installed"
    assert {name: from_file[name] for name in declared} == declared


def test_every_requirement_is_pinned() -> None:
    """No range, no wildcard, in any requirements file."""
    for path in sorted(ROOT.glob("requirements*.txt")):
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            assert "==" in line, f"{path.name}: {line!r} is not pinned"
