ARG PYTHON_BASE_IMAGE=python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --uid 10001 labops
COPY --chown=labops:labops . /app

USER labops
EXPOSE 8787

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=2)"]

ENTRYPOINT []
CMD ["python", "-B", "-m", "labops", "web", "--workspace", "/tmp/labops-output", "--host", "0.0.0.0", "--port", "8787", "--run-demo"]
