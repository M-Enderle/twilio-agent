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
       supervisor \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js 20.x
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*


FROM base AS dependencies

# Copy full project to build/install via PEP 621
COPY . .

# Install project and dependencies into system site-packages
RUN pip install --no-cache-dir .


FROM base AS svelte-build

WORKDIR /app/dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ .
RUN npx svelte-kit sync && npm run build


FROM base AS production

# Create non-root user and prepare directories
RUN mkdir -p /app/logs \
    && mkdir -p /app/ai_cache

# Copy site-packages and deps layer
COPY --from=dependencies /usr/local /usr/local

# Copy application source (for static/templates and runtime assets)
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
