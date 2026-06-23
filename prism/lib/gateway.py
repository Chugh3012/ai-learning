from __future__ import annotations

from prism.lib import foundry
from prism.lib.config import config_json

class ModelGateway:
    # One access point for LLM models: per-task model selection (config-driven in
    # config/models.json, so a model can be swapped or rolled out gradually without code) and
    # per-model cost accounting. Endpoint stays the Foundry project; only the deployment varies.
    def __init__(self, endpoint: str, default: str = "mini"):
        self.endpoint = endpoint
        cfg = config_json("models.json")
        tasks = cfg.get("tasks")
        pricing = cfg.get("pricing")
        self._tasks = tasks if isinstance(tasks, dict) else {}
        self._pricing = pricing if isinstance(pricing, dict) else {}
        self._default = default or "mini"
        self._client = None

    def model_for(self, task: str) -> str:
        return self._tasks.get(task) or self._default

    def client(self):
        if self._client is None:
            self._client = foundry.openai_client(self.endpoint)
        return self._client

    def cost_usd(self) -> float:
        return foundry.cost_usd(self._pricing)
