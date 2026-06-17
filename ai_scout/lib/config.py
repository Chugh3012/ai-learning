from __future__ import annotations

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
DATA_DIR = REPO_ROOT / "data"
KB_DIR = DATA_DIR / "kb"
KB_PATH = KB_DIR / "kb.sqlite"
DRAFTS_DIR = REPO_ROOT / "drafts"
DIGESTS_DIR = REPO_ROOT / "digests"
FOUNDRY_DIR = REPO_ROOT / ".foundry"
ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE = REPO_ROOT / ".env.example"

def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out

def load_env() -> dict[str, str]:
    env = _parse_env_file(ENV_FILE)
    keys = set(_parse_env_file(ENV_EXAMPLE))
    env.update({k: v for k, v in os.environ.items() if k in keys})
    return env

def env_value(key: str, default: str = "") -> str:
    if key in os.environ:
        return os.environ[key]
    return _parse_env_file(ENV_FILE).get(key, default)

def config_json(name: str) -> dict:
    try:
        return json.loads((CONFIG_DIR / name).read_text(encoding="utf-8"))
    except Exception:
        return {}
