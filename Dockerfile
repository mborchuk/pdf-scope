# PDF Scope — container image for running the local web UI.
#
# The application is a local-use inspection tool with no authentication (see
# SECURITY.md). Publish the port to the loopback interface only:
#
#   docker build -t pdf-scope .
#   docker run --rm -p 127.0.0.1:8000:8000 pdf-scope
#
# PyMuPDF bundles MuPDF, so no system libraries are needed beyond the base image.

# ----------------------------------------------------------------- build stage
# Wheels are resolved and installed here so the final image carries no build
# tooling, no pip cache and no compiler.
FROM python:3.14-slim AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /src

# Dependencies first: this layer is rebuilt only when the pins change.
COPY requirements.txt ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# The package itself, installed into the same virtual environment. Static UI
# assets travel with it (see pyproject package-data).
COPY pyproject.toml README.md LICENSE ./
COPY pdf_scope ./pdf_scope
RUN /opt/venv/bin/pip install --no-cache-dir --no-deps .

# ---------------------------------------------------------------- runtime stage
FROM python:3.14-slim AS runtime

LABEL org.opencontainers.image.title="PDF Scope" \
      org.opencontainers.image.description="Inspect the structure and contents of PDF files in a local web UI." \
      org.opencontainers.image.source="https://github.com/mborchuk/pdf-scope" \
      org.opencontainers.image.licenses="MIT"

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Artifacts live on a path that can be mounted; the server empties it on
    # every start, so nothing here is durable state.
    PDF_SCOPE_WORKSPACE=/data/workspace

COPY --from=build /opt/venv /opt/venv

# Unprivileged user. /data is owned by it so a bind mount can be written to.
RUN useradd --create-home --uid 10001 pdfscope \
 && mkdir -p /data/workspace \
 && chown -R pdfscope:pdfscope /data

USER pdfscope
WORKDIR /home/pdfscope
VOLUME ["/data/workspace"]
EXPOSE 8000

# 0.0.0.0 is required for the port to be reachable from outside the container.
# Restrict exposure on the host side with -p 127.0.0.1:8000:8000.
ENTRYPOINT ["pdf-scope"]
CMD ["--host", "0.0.0.0", "--port", "8000"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/status', timeout=4).status == 200 else 1)"
