from __future__ import annotations

import html
import logging
import os
import time

import azure.functions as func
from azure.core.exceptions import ResourceNotFoundError
from azure.data.tables import TableServiceClient, UpdateMode
from azure.identity import DefaultAzureCredential

app = func.FunctionApp()

_ACTIONS: dict[str, tuple[str, float]] = {
    "up": ("vote", 1.0),
    "down": ("vote", -1.0),
    "save": ("save", 1.0),
    "click": ("click", 1.0),
}

_TABLE_SERVICE: TableServiceClient | None = None

def _tables() -> TableServiceClient:
    global _TABLE_SERVICE
    if _TABLE_SERVICE is None:
        account = os.environ["AzureWebJobsStorage__accountName"]
        _TABLE_SERVICE = TableServiceClient(
            endpoint=f"https://{account}.table.core.windows.net",
            credential=DefaultAzureCredential(),
        )
    return _TABLE_SERVICE

def _page(message: str) -> func.HttpResponse:
    body = (
        '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<div style="font-family:system-ui,Segoe UI,Arial,sans-serif;max-width:420px;'
        'margin:18vh auto;text-align:center;color:#222">'
        f'<div style="font-size:40px">✓</div><h2 style="margin:8px 0">{html.escape(message)}</h2>'
        '<p style="color:#777;font-size:14px">ai-scout is tuning your next digest. '
        'You can close this tab.</p></div>'
    )
    return func.HttpResponse(body, mimetype="text/html", status_code=200)

@app.route(route="f", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def feedback(req: func.HttpRequest) -> func.HttpResponse:
    token = (req.params.get("t") or "").strip()
    if not token:
        return func.HttpResponse("Missing token.", status_code=400)

    try:
        tokens = _tables().get_table_client("feedbacktokens")
        entity = tokens.get_entity(partition_key="tok", row_key=token)
    except ResourceNotFoundError:
        return func.HttpResponse("This feedback link is not valid.", status_code=404)
    except Exception:
        logging.exception("feedback: token lookup failed")
        return func.HttpResponse("Temporary error, please try again.", status_code=503)

    action = str(entity.get("action", ""))
    if action not in _ACTIONS:
        return func.HttpResponse("Unknown action.", status_code=400)
    item_id = str(entity.get("itemId", ""))
    lens = str(entity.get("lens", ""))
    if not lens:
        return func.HttpResponse("This feedback link is not valid.", status_code=404)
    row_key, value = _ACTIONS[action]

    try:
        events = _tables().get_table_client("feedbackevents")
        events.upsert_entity(
            {
                "PartitionKey": item_id,
                "RowKey": f"{lens}:{row_key}",
                "lens": lens,
                "value": value,
                "action": action,
                "ts": int(time.time()),
            },
            mode=UpdateMode.REPLACE,
        )
    except Exception:
        logging.exception("feedback: event write failed")
        return func.HttpResponse("Temporary error, please try again.", status_code=503)

    if action == "click":
        url = str(entity.get("url", ""))
        if url.startswith(("http://", "https://")):
            return func.HttpResponse(status_code=302, headers={"Location": url})
        return _page("Thanks — noted.")

    messages = {"up": "Thanks — more like this 👍", "down": "Got it — less like this 👎",
                "save": "Saved to learn from ⭐"}
    return _page(messages.get(action, "Thanks — noted."))
