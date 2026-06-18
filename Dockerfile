# AgentVision — reliable headless rendering with Chromium deps baked in.
# Build:  docker build -t agentvision .
# Run:    docker run --rm -e ANTHROPIC_API_KEY -v "$PWD:/work" agentvision demo
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

# System deps for OCR + PDF (Chromium + its libs already ship in the base image).
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-eng poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY examples ./examples

RUN pip install --no-cache-dir ".[all]"

WORKDIR /work
ENTRYPOINT ["agentvision"]
CMD ["doctor"]
