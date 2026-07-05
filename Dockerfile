FROM node:22-bookworm-slim AS node

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY --from=node /usr/local/ /usr/local/

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
    && npm install -g @earendil-works/pi-coding-agent@0.80.3 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /root/.pi/agent/skills /workspace/skills

# add specific model configs (e.g. for improving kimi-code usage)
COPY pilot/models.json /root/.pi/agent/models.json

# add pi.lot agents.md instructions
COPY pilot/pi.lot_AGENTS.md /root/.pi/agent/AGENTS.md

# load pi.lot built-in skills
COPY pilot/skills /root/.pi/agent/skills/

# Expose persistent workspace skills under the global pi skill tree too.
# pi.lot also passes `--skill /workspace/skills` at runtime because
# /workspace/skills is not a documented auto-discovery directory.
RUN ln -s /workspace/skills /root/.pi/agent/skills

# load pi.lot built-in extensions globally
COPY pilot/pi_extensions/ /root/.pi/agent/extensions/

WORKDIR /app
COPY pilot/requirements.txt ./
RUN pip install -r requirements.txt
COPY pilot ./pilot

RUN mkdir -p /workspace/data

# Startup tasks:
# - remove stale workspace copies of bundled extensions
# - start cron
# - sync cronjobs
# - start pi.lot
CMD ["sh", "-c", "set -eu; for ext in /root/.pi/agent/extensions/*.ts; do [ -e \"$ext\" ] || continue; base=${ext##*/}; rm -f \"/workspace/.pi/extensions/$base\"; done; cron; python /root/.pi/agent/skills/cronjobs/scripts/cron_cli.py sync || true; exec python -m pilot"]
