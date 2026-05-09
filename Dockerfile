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
        nodejs \
        npm \
    && npm install -g @earendil-works/pi-coding-agent@latest \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY pilot ./pilot

CMD ["python", "-m", "pilot"]
