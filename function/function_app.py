"""ai-scout feedback capture (P7) — tiny passwordless Azure Function.

One HTTP route receives a click from a daily-email feedback link. The link carries an
opaque, single-purpose token (unguessable, minted per item+action at send time and stored
in the `feedbacktokens` table). The function validates the token and records the gesture as
an *event* in the `feedbackevents` table. It never touches the SQLite KB — capture is fully
decoupled from the pipeline (no concurrent-write risk). A daily kb_sync step drains events
into the KB and recomputes ranking affinity.

Feedback model (borrowed from NewsBlur's proven "intelligence trainer", kept minimal):
gestures are *additive affinity*, not a novel algorithm. Up/down share one row so they
toggle cleanly; save and click are separate positive signals.

  action  -> events row (PartitionKey=item_id)        meaning
  up      -> RowKey='vote'  value=+1                   👍  (overwrites a prior 👎)
  down    -> RowKey='vote'  value=-1                   👎  (overwrites a prior 👍)
  save    -> RowKey='save'  value=+1                   bookmark to learn from
  click   -> RowKey='click' value=+1                   implicit interest (then 302 to source)

Passwordless: DefaultAzureCredential uses the Function's system-assigned managed identity
(Storage Table Data Contributor on the function storage account). No keys or connection
strings. The storage account name comes from the host setting AzureWebJobsStorage__accountName.
"""
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

# action -> (events RowKey suffix, value). Up/down collapse to one 'vote' row (per user) so a
# later vote overwrites. The event RowKey is '<user>:<suffix>' so users vote independently.
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
    except Exception:  # noqa: BLE001
        logging.exception("feedback: token lookup failed")
        return func.HttpResponse("Temporary error, please try again.", status_code=503)

    action = str(entity.get("action", ""))
    if action not in _ACTIONS:
        return func.HttpResponse("Unknown action.", status_code=400)
    item_id = str(entity.get("itemId", ""))
    user = str(entity.get("user", "")) or "primary"
    row_key, value = _ACTIONS[action]

    try:
        events = _tables().get_table_client("feedbackevents")
        events.upsert_entity(
            {
                "PartitionKey": item_id,
                "RowKey": f"{user}:{row_key}",
                "user": user,
                "value": value,
                "action": action,
                "ts": int(time.time()),
            },
            mode=UpdateMode.REPLACE,
        )
    except Exception:  # noqa: BLE001
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
