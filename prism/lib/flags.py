from __future__ import annotations

from prism.lib.config import config_json

def enabled(name: str, default: bool = True) -> bool:
    # Feature kill-switch read from config/flags.json. Lets a feature be turned off in config
    # (no code/deploy) and is the seam for canary rollout. Unknown name -> default.
    val = config_json("flags.json").get(name)
    return default if val is None else bool(val)
