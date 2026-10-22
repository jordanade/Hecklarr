FROM python:3.13-alpine@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a
LABEL org.opencontainers.image.source="https://github.com/jordanade/Hecklarr"
LABEL org.opencontainers.image.licenses="GPL-3.0-only"
RUN apk add --no-cache tzdata \
    && python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.13/ensurepip
WORKDIR /app
# Generated assets can be private on the build host; the service runs as UID
# 1000 and must be able to read every public asset in the resulting image.
COPY --chmod=644 index.html app.js style.css icon.png tmdb-logo.svg ./
COPY --chmod=644 LICENSE THIRD_PARTY_NOTICES.md ./
COPY src ./src
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1 CONFIG_DIR=/config TZ=America/Detroit
USER 1000:1000
EXPOSE 6162
HEALTHCHECK --interval=60s --timeout=5s --start-period=180s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6162/api/health')"
CMD ["python", "-m", "hecklarr"]
