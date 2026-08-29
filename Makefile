# Developer shortcuts. All commands use the local virtual environment.
VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
PORT ?= 8000
IMAGE ?= pdf-scope

.PHONY: help venv install install-dev run dev docker-build docker-run test lint format check clean

help:
	@echo "make install      create .venv and install runtime dependencies"
	@echo "make install-dev  also install pytest and ruff"
	@echo "make run          start the server on http://127.0.0.1:$(PORT)"
	@echo "make dev          start the server with auto-reload"
	@echo "make docker-build build the container image ($(IMAGE))"
	@echo "make docker-run   run the image, published on 127.0.0.1:$(PORT) only"
	@echo "make test         run the test suite"
	@echo "make lint         ruff check + ruff format --check"
	@echo "make format       apply ruff format and fixable lint rules"
	@echo "make check        lint and test"
	@echo "make clean        remove caches, build output and the workspace"

venv:
	test -d $(VENV) || python3 -m venv $(VENV)

install: venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -r requirements.txt

install-dev: venv
	$(PIP) install -q --upgrade pip
	$(PIP) install -r requirements-dev.txt

run:
	$(PY) -m pdf_scope --port $(PORT)

dev:
	$(PY) -m pdf_scope --port $(PORT) --reload

# --load puts the result in the local image store. It is the default with the
# classic builder but not with a container-driver buildx builder, where the image
# would otherwise stay in the build cache only.
docker-build:
	docker build --load -t $(IMAGE) .

# The port is published on loopback only: the app has no authentication.
docker-run:
	docker run --rm -p 127.0.0.1:$(PORT):8000 $(IMAGE)

test:
	$(PY) -m pytest

lint:
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

format:
	$(VENV)/bin/ruff format .
	$(VENV)/bin/ruff check --fix .

check: lint test

clean:
	rm -rf .pytest_cache .ruff_cache .workspace build dist *.egg-info
	find . -name __pycache__ -type d -not -path "./.venv/*" -exec rm -rf {} +
