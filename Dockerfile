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
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# deploy.sh passes CACHEBUST to refresh npm. Pi 1.6.0 supplies the native
# OpenAI subscription catalog, including GPT-6.2 Astra and GPT-6.2 Sol.
ARG CACHEBUST=unset
RUN npm install -g npm@latest \
    && npm install -g @earendil-works/pi-coding-agent@1.6.0

RUN mkdir -p /root/.pi/agent/skills /workspace/skills

# add specific model configs (e.g. for improving kimi-code usage)
COPY pilot/models.json /root/.pi/agent/models.json

# Retry transient provider errors twice, after 20s and 40s.
COPY pilot/settings.json /root/.pi/agent/settings.json

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
COPY pilot/BEHAVIOR.md ./BEHAVIOR.md
COPY pilot/requirements.txt ./
# CACHEBUST again: see comment above the npm install.
# Note: we deliberately do NOT pass --upgrade to the requirements install — the
# pinned versions in pilot/requirements.txt must be respected. Only the pip CLI
# itself is upgraded here, plus a layer-cache bust so `pip install` actually runs.
ARG CACHEBUST=unset
RUN pip install --upgrade pip \
    && pip install -r requirements.txt
COPY pilot ./pilot
COPY entrypoint.sh /app/entrypoint.sh

RUN mkdir -p /workspace/data

# Startup tasks:
# - remove stale workspace copies of bundled extensions
# - start cron
# - sync cronjobs
# - start pi.lot
CMD ["sh", "-c", "set -eu; sh /app/entrypoint.sh; for ext in /root/.pi/agent/extensions/*.ts; do [ -e \"$ext\" ] || continue; base=${ext##*/}; rm -f \"/workspace/.pi/extensions/$base\"; done; cron; python /root/.pi/agent/skills/cronjobs/scripts/cron_cli.py sync || true; exec python -m pilot"]
