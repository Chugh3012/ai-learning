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


def log_usage(stage: str, resp) -> None:
    """Print token usage for one Foundry call so per-run cost is observable in logs.
    Best-effort: silently does nothing if the response carries no usage."""
    try:
        u = resp.usage
        print(f"{stage}: tokens prompt={u.prompt_tokens} completion={u.completion_tokens} "
              f"total={u.total_tokens}")
    except Exception:  # noqa: BLE001
        pass

