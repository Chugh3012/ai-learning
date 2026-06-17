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

def log_usage(stage: str, resp) -> None:
    try:
        u = resp.usage
        _USAGE["prompt"] += int(u.prompt_tokens)
        _USAGE["completion"] += int(u.completion_tokens)
        _USAGE["total"] += int(u.total_tokens)
        _USAGE["calls"] += 1
        print(f"{stage}: tokens prompt={u.prompt_tokens} completion={u.completion_tokens} "
              f"total={u.total_tokens}")
    except Exception:
        pass

def usage_snapshot() -> dict:
    return dict(_USAGE)
