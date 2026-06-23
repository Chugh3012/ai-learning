from __future__ import annotations

def openai_client(endpoint: str):
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    return project.get_openai_client()

def embed(endpoint: str, deployment: str, texts: list[str], dims: int = 256) -> list[list[float]]:
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AzureOpenAI

    account = endpoint.split("/api/projects/", 1)[0]
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
    client = AzureOpenAI(azure_endpoint=account, azure_ad_token_provider=token_provider,
                         api_version="2024-10-21")
    resp = client.embeddings.create(model=deployment, input=texts, dimensions=dims)
    return [d.embedding for d in resp.data]

_USAGE = {"prompt": 0, "completion": 0, "total": 0, "calls": 0}
_BY_MODEL: dict[str, dict[str, int]] = {}

def log_usage(stage: str, resp, model: str = "") -> None:
    try:
        u = resp.usage
        _USAGE["prompt"] += int(u.prompt_tokens)
        _USAGE["completion"] += int(u.completion_tokens)
        _USAGE["total"] += int(u.total_tokens)
        _USAGE["calls"] += 1
        m = _BY_MODEL.setdefault(model or "default", {"prompt": 0, "completion": 0})
        m["prompt"] += int(u.prompt_tokens)
        m["completion"] += int(u.completion_tokens)
        print(f"{stage}: tokens prompt={u.prompt_tokens} completion={u.completion_tokens} "
              f"total={u.total_tokens}")
    except Exception:
        pass

def usage_snapshot() -> dict:
    return dict(_USAGE)

_PRICE_IN_PER_M = 0.40
_PRICE_OUT_PER_M = 1.60

def cost_usd(pricing: dict | None = None) -> float:
    pricing = pricing or {}
    if not _BY_MODEL:
        return (_USAGE["prompt"] / 1e6 * _PRICE_IN_PER_M
                + _USAGE["completion"] / 1e6 * _PRICE_OUT_PER_M)
    total = 0.0
    for model, u in _BY_MODEL.items():
        p = pricing.get(model, {})
        total += (u["prompt"] / 1e6 * float(p.get("in", _PRICE_IN_PER_M))
                  + u["completion"] / 1e6 * float(p.get("out", _PRICE_OUT_PER_M)))
    return total
