# syntax=docker/dockerfile:1

FROM python:3.10-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

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
       supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20.x
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*


FROM base AS dependencies

# Copy ONLY dependency-defining files (cache-friendly: code changes won't bust this layer)
COPY pyproject.toml poetry.lock ./

# Create minimal package stub so pip can resolve the project
RUN mkdir -p twilio_agent && touch twilio_agent/__init__.py

# Install deps with persistent cache mount across builds
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install .


FROM base AS svelte-build

WORKDIR /app/dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci
COPY dashboard/ .
RUN npx svelte-kit sync && npm run build


FROM base AS production

# Prepare directories
RUN mkdir -p /app/logs \
    && mkdir -p /app/ai_cache

# Copy installed Python packages from dependencies stage
COPY --from=dependencies /usr/local /usr/local

# Copy application source
COPY . .

# Copy SvelteKit build
COPY --from=svelte-build /app/dashboard/build /app/dashboard/build
COPY --from=svelte-build /app/dashboard/node_modules /app/dashboard/node_modules
COPY --from=svelte-build /app/dashboard/package.json /app/dashboard/package.json

# Copy supervisord config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

EXPOSE 8000 3000

# Run both services via supervisord
CMD ["supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
