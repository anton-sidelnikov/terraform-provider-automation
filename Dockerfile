FROM python:3.12.11-slim-bookworm@sha256:c00fc7b44d844b6da22861ec24af43968a5200eac4ec607b4725d585165d6b49

LABEL org.opencontainers.image.source="https://github.com/anton-sidelnikov/terraform-provider-automation" \
      org.opencontainers.image.title="OTC Agent Planning API" \
      org.opencontainers.image.description="Credential-free planning, health, and metrics API" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONHASHSEED=0 \
    PYTHONPATH=/app/src

WORKDIR /app
COPY --chown=65532:65532 src/ src/
COPY --chown=65532:65532 config/ config/

USER 65532:65532
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2).read()"]

ENTRYPOINT ["python", "-m", "otc_agent.api"]
CMD ["--host", "0.0.0.0", "--port", "8080"]
