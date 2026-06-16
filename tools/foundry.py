"""Shared Microsoft Foundry client factory (passwordless).

One place to build the project's OpenAI-compatible client via the Foundry SDK, used by
rank.py, draft.py, and notify.py. Auth is Entra: az login locally, OIDC managed identity
in CI. No keys.
"""
from __future__ import annotations


def openai_client(endpoint: str):
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    project = AIProjectClient(endpoint=endpoint, credential=DefaultAzureCredential())
    return project.get_openai_client()


def embed(endpoint: str, deployment: str, texts: list[str], dims: int = 256) -> list[list[float]]:
    """Return an embedding vector per input text (passwordless). `dims` uses text-embedding-3's
    native dimension-reduction so vectors stay small/cheap to store. Raises on failure — callers
    treat embedding as optional and degrade gracefully.

    Embeddings are served by the ACCOUNT's Azure OpenAI endpoint, not the project's openai/v1
    path (which only serves chat); we derive the account endpoint from the project endpoint
    (strip the /api/projects/<name> suffix) and auth with the same Entra credential."""
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AzureOpenAI

    account = endpoint.split("/api/projects/", 1)[0]
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
    client = AzureOpenAI(azure_endpoint=account, azure_ad_token_provider=token_provider,
                         api_version="2024-10-21")
    resp = client.embeddings.create(model=deployment, input=texts, dimensions=dims)
    return [d.embedding for d in resp.data]


def log_usage(stage: str, resp) -> None:
    """Print token usage for one Foundry call so per-run cost is observable in logs.
    Best-effort: silently does nothing if the response carries no usage."""
    try:
        u = resp.usage
        print(f"{stage}: tokens prompt={u.prompt_tokens} completion={u.completion_tokens} "
              f"total={u.total_tokens}")
    except Exception:  # noqa: BLE001
        pass

