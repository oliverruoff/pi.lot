FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        curl \
        git \
        openssh-client \
        openssh-server \
        ca-certificates \
        tzdata \
        cron \
        nodejs \
        npm \
    && npm install -g @earendil-works/pi-coding-agent@latest \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /root/.pi/agent \
    && printf '%s\n' \
        '{' \
        '  "providers": {' \
        '    "kimi-coding": {' \
        '      "headers": { "User-Agent": "gsd-pi" }' \
        '    }' \
        '  }' \
        '}' \
        > /root/.pi/agent/models.json

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY pilot ./pilot
COPY pilot/skills /root/.agents/skills
COPY pi_extensions/ /root/.pi/agent/extensions/

RUN mkdir -p /workspace/data

# Startup tasks:
# - start cron
# - sync cronjobs
# - start pi.lot
CMD ["sh", "-c", "set -eu; \
    cron; \
    python /root/.agents/skills/cronjobs/scripts/cron_cli.py sync || true; \
    exec python -m pilot"]
