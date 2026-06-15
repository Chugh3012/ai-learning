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
