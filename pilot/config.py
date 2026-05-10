from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    workdir: str
    behavior_prompt: str
    log_level: str
    pi_command: str
    pi_args: list[str]
    telegram_parse_mode: str
    data_dir: str


def _read_behavior() -> str:
    direct = os.getenv("PILOT_BEHAVIOR_PROMPT")
    if direct is not None:
        return direct
    path = os.getenv("PILOT_BEHAVIOR_PROMPT_PATH") or os.getenv("BEHAVIOR_PROMPT_PATH")
    if path:
        return Path(path).read_text(encoding="utf-8")
    return "You are pi.lot, a helpful AI coding assistant connected through Telegram."


def load_config() -> Config:
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    workdir = os.getenv("PILOT_WORKDIR") or os.getenv("WORKDIR") or "/workspace"
    pi_command = os.getenv("PI_COMMAND", "pi")
    extra_args = os.getenv("PI_ARGS", "")
    pi_args = ["--mode", "rpc"] + ([a for a in extra_args.split(" ") if a] if extra_args else [])

    return Config(
        telegram_bot_token=token,
        workdir=workdir,
        behavior_prompt=_read_behavior(),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        pi_command=pi_command,
        pi_args=pi_args,
        telegram_parse_mode=os.getenv("TELEGRAM_PARSE_MODE", "MarkdownV2"),
        data_dir=os.getenv("PILOT_DATA_DIR", "/data"),
    )
