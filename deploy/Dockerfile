FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
RUN python -m pip install --no-cache-dir ".[gateway]"
ENV EMU_MEM_HOME=/data
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"
CMD ["emu-mem", "gateway", "--host", "0.0.0.0", "--port", "8000"]
