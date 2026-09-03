"""Load pi.lot settings from the environment and persistent storage."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from dotenv import load_dotenv


WORKSPACE_SKILLS_DIR = "/workspace/skills"
DEFAULT_DATA_DIR = "/workspace/data"
DEFAULT_WORKDIR = "/workspace"
DEFAULT_BEHAVIOR_PATH = "/workspace/BEHAVIOR.md"
DEFAULT_BEHAVIOR_TEMPLATE_PATH = "/app/BEHAVIOR.md"
DEFAULT_PI_COMMAND = "pi"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_PARSE_MODE = "MarkdownV2"


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
    main_user_id: int | None = None
    main_chat_id: int | None = None
    behavior_prompt_path: str = ""


def _env(*keys: str) -> str | None:
    """Return the first non-empty environment variable value for the given keys."""
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return None


def _load_behavior(persisted: dict) -> tuple[str, str]:
    """Load the behavior file, creating it once from legacy configuration."""
    path = Path(DEFAULT_BEHAVIOR_PATH)
    if path.exists():
        return path.read_text(encoding="utf-8"), str(path)

    template = Path(DEFAULT_BEHAVIOR_TEMPLATE_PATH)
    prompt = persisted.get("behavior_prompt")
    if not prompt and template.exists():
        prompt = template.read_text(encoding="utf-8")
    if not prompt:
        prompt = "You are pi.lot, a helpful personal assistant available through Telegram."
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(prompt).rstrip() + "\n", encoding="utf-8")
    return str(prompt), str(path)


def _load_persisted_config(data_dir: str) -> dict:
    path = Path(data_dir) / "config.json"
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _as_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _build_pi_args(persisted: dict) -> list[str]:
    """Build pi CLI arguments from environment or persisted config."""
    base_args = ["--mode", "rpc", "--skill", WORKSPACE_SKILLS_DIR]

    extra_args = os.getenv("PI_ARGS")
    if extra_args is not None:
        split = [a for a in extra_args.split(" ") if a]
        return base_args + split

    persisted_args = persisted.get("pi_args")
    if isinstance(persisted_args, list):
        return [str(a) for a in persisted_args]

    return base_args


def persist_config(cfg: Config) -> None:
    path = Path(cfg.data_dir) / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(".json.tmp")
    data = asdict(cfg)
    data.pop("behavior_prompt", None)
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_config() -> Config:
    load_dotenv()

    data_dir = os.getenv("PILOT_DATA_DIR", DEFAULT_DATA_DIR)
    os.environ.setdefault("PI_CODING_AGENT_SESSION_DIR", str(Path(data_dir) / "pi-sessions"))

    persisted = _load_persisted_config(data_dir)

    token = _env("TELEGRAM_BOT_TOKEN", "BOT_TOKEN") or persisted.get("telegram_bot_token")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")

    workdir = _env("PILOT_WORKDIR", "WORKDIR") or persisted.get("workdir") or DEFAULT_WORKDIR
    behavior_prompt, behavior_prompt_path = _load_behavior(persisted)
    pi_command = _env("PI_COMMAND") or persisted.get("pi_command") or DEFAULT_PI_COMMAND
    pi_args = _build_pi_args(persisted)

    cfg = Config(
        telegram_bot_token=str(token),
        workdir=str(workdir),
        behavior_prompt=behavior_prompt,
        log_level=_env("LOG_LEVEL") or persisted.get("log_level") or DEFAULT_LOG_LEVEL,
        pi_command=str(pi_command),
        pi_args=pi_args,
        telegram_parse_mode=_env("TELEGRAM_PARSE_MODE") or persisted.get("telegram_parse_mode") or DEFAULT_PARSE_MODE,
        data_dir=data_dir,
        main_user_id=_as_int(persisted.get("main_user_id")),
        main_chat_id=_as_int(persisted.get("main_chat_id")),
        behavior_prompt_path=behavior_prompt_path,
    )

    persist_config(cfg)
    return cfg
