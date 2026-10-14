FROM python:3.13-alpine@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a
RUN apk add --no-cache tzdata
WORKDIR /app
COPY app.py index.html app.js style.css icon.png tmdb-logo.svg ./
ENV PYTHONUNBUFFERED=1 CONFIG_DIR=/config TZ=America/Detroit
USER 1000:1000
EXPOSE 6162
HEALTHCHECK --interval=60s --timeout=5s --start-period=180s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6162/api/health')"
CMD ["python", "app.py"]
