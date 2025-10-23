# syntax=docker/dockerfile:1

FROM python:3.10-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps (build tools + libs for matplotlib, Levenshtein, etc.)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       curl \
       libffi-dev \
       zlib1g-dev \
       libjpeg62-turbo-dev \
       libfreetype6-dev \
       libpng-dev \
    && rm -rf /var/lib/apt/lists/*


FROM base AS dependencies

# Copy full project to build/install via PEP 621
COPY . .

# Install project and dependencies into system site-packages
RUN pip install --no-cache-dir .


FROM base AS production

# Create non-root user and prepare directories
RUN useradd -m -u 10001 appuser \
    && mkdir -p /app/logs \
    && mkdir -p /app/ai_cache \
    && chown -R appuser:appuser /app

# Copy site-packages and deps layer
COPY --from=dependencies /usr/local /usr/local

# Copy application source (for static/templates and runtime assets)
COPY . .

# Fix ownership after copying files
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Default command: run FastAPI via uvicorn
CMD ["uvicorn", "twilio_agent.conversation_flow:app", "--host", "0.0.0.0", "--port", "8000", "--ws", "auto", "--workers", "4"]


