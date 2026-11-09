FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends make && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY rcwa/ ./rcwa/
COPY policies/ ./policies/
COPY clusters/ ./clusters/
COPY docs/ ./docs/
COPY tests/ ./tests/
COPY Makefile ./

RUN pip install --no-cache-dir -e ".[dev]"

CMD ["make", "test"]
