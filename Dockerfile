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

RUN mkdir -p /root/.pi/agent /workspace/skills

# add specific model configs (e.g. for improving kimi-code usage)
COPY pilot/models.json /root/.pi/agent/models.json

# add pi.lot agents.md instructions
COPY pilot/pi.lot_AGENTS.md /root/.pi/agent/AGENTS.md

# load pi.lot built-in skills
COPY pilot/skills /root/.pi/agent/skills/

# whenever new skills are created under /root/.pi/agent/skills they will be 
# automatically symlinked to /workspace/skills for later persistence
RUN ln -s /workspace/skills /root/.pi/agent/skills

# load pi.lot built-in extensions 
COPY pilot/pi_extensions/ /root/.pi/agent/extensions/

WORKDIR /app
COPY pilot/requirements.txt ./
RUN pip install -r requirements.txt
COPY pilot ./pilot

RUN mkdir -p /workspace/data

# Startup tasks:
# - start cron
# - sync cronjobs
# - start pi.lot
CMD ["sh", "-c", "set -eu; \
    cron; \
    python /root/.pi/agent/skills/cronjobs/scripts/cron_cli.py sync || true; \
    exec python -m pilot"]
