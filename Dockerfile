FROM python:3.12.10-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYSPARK_PYTHON=/usr/local/bin/python \
    TZ=America/Lima

RUN apt-get update \
    && apt-get install --yes --no-install-recommends openjdk-17-jre-headless tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip==25.0.1 \
    && pip install --no-cache-dir -r requirements.txt

COPY . ./
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "scripts/validate_environment.py"]

