# --- stage 1: fetch frontend vendor assets ---
FROM node:20-slim AS assets
WORKDIR /assets
RUN apt-get update && apt-get install -y --no-install-recommends curl unzip jq ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# pdf.js prebuilt viewer (full web app, not on npm) — always grab the latest GitHub release asset.
# pdf.js publishes both a "-dist.zip" and a "-legacy-dist.zip" asset; explicitly exclude the
# legacy build so exactly one URL comes out (a bare endswith("dist.zip") matches both).
RUN curl -sL "$(curl -s https://api.github.com/repos/mozilla/pdf.js/releases/latest \
      | jq -r '.assets[] | select(.name | endswith("dist.zip") and (contains("legacy") | not)) | .browser_download_url')" \
      -o pdfjs.zip \
    && mkdir -p vendor/pdfjs \
    && unzip -q pdfjs.zip -d vendor/pdfjs

# highlight.js: the project no longer attaches a prebuilt CDN-style zip to its GitHub
# releases (the release used here, 11.12.0, has zero release assets), so the brief's
# "download the release zip" step has nothing to fetch. highlight.js instead publishes
# its prebuilt browser bundle as a separate npm package, @highlightjs/cdn-assets, which
# ships the same highlight.min.js + styles/*.css previously found in the release zip
# (viewer.html loads vendor/highlight/highlight.min.js and
# vendor/highlight/styles/github-dark.min.css — both present here) — fetched via npm below.

# marked, DOMPurify (HTML sanitizer, used before innerHTML injection of rendered markdown
# — added post-brief per Task 16 security review), and highlight.js's CDN bundle — all via
# npm. marked no longer publishes a minified single-file build on npm (only an ESM build
# and this browser-ready UMD build, both unminified) — the UMD build sets window.marked
# exactly like the old marked.min.js did, so it's copied to the same runtime filename
# (viewer.html already references /static/vendor/marked/marked.min.js) even though it is
# not actually minified.
RUN npm install marked dompurify @highlightjs/cdn-assets \
    && mkdir -p vendor/marked vendor/dompurify vendor/highlight \
    && cp node_modules/marked/lib/marked.umd.js vendor/marked/marked.min.js \
    && cp node_modules/dompurify/dist/purify.min.js vendor/dompurify/purify.min.js \
    && cp node_modules/@highlightjs/cdn-assets/highlight.min.js vendor/highlight/highlight.min.js \
    && cp -r node_modules/@highlightjs/cdn-assets/styles vendor/highlight/styles

# --- stage 2: application image ---
FROM python:3.12-slim
WORKDIR /srv/app

RUN apt-get update && apt-get install -y --no-install-recommends \
      libreoffice-writer \
      libreoffice-core \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY scripts/ scripts/
COPY --from=assets /assets/vendor/pdfjs app/static/vendor/pdfjs
COPY --from=assets /assets/vendor/highlight app/static/vendor/highlight
COPY --from=assets /assets/vendor/marked app/static/vendor/marked
COPY --from=assets /assets/vendor/dompurify app/static/vendor/dompurify

RUN mkdir -p /data/files /data/cache /data/db \
    && chown -R appuser:appuser /srv/app /data

USER appuser
EXPOSE 8000

ENV FILES_ROOT=/data/files \
    DB_PATH=/data/db/docviewer.sqlite3 \
    CACHE_DIR=/data/cache

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
