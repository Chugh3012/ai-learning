"""FeedbackStore — passwordless Azure Tables access for feedback tokens + gesture events.

The pipeline side of the feedback loop: mint per-(lens,item,action) tokens for delivery links,
drain the gesture events the Function records, and record outcome votes (the agent's merge = 👍).
Everything is keyed by the opaque LENS — no identity is embedded. The Function (function/) is the
consumer side and stays standalone; this is what the pipeline + agent use.
"""
from __future__ import annotations

import secrets
import time

# events 'action' -> (events RowKey suffix, value). up/down collapse to one 'vote' row per lens.
_ACTIONS = ("up", "down", "save", "click")
_ACTION_TO_ROW = {"up": "vote", "down": "vote", "save": "save", "click": "click"}


class FeedbackStore:
    """Wraps the `feedbacktokens` + `feedbackevents` tables. Inject the storage account (DI);
    a missing account makes minting return {} and draining return [] (graceful)."""

    def __init__(self, account: str):
        self.account = account

    @property
    def enabled(self) -> bool:
        return bool(self.account)

    def _table(self, name: str):
        from azure.data.tables import TableServiceClient
        from azure.identity import DefaultAzureCredential
        return TableServiceClient(
            endpoint=f"https://{self.account}.table.core.windows.net",
            credential=DefaultAzureCredential(),
        ).get_table_client(name)

    def mint_tokens(self, lens: str, items: list[tuple]) -> dict[int, dict[str, str]]:
        """Mint an opaque token per (lens, item, action) into `feedbacktokens`. Returns
        {item_id: {action: token}}; {} (graceful) when the store is unavailable. The token carries
        only the opaque lens (`<user_id>:<profile_id>`)."""
        if not self.enabled:
            return {}
        try:
            from azure.data.tables import UpdateMode
            table = self._table("feedbacktokens")
        except Exception as e:  # noqa: BLE001
            print(f"deliver: feedback tokens unavailable ({e}); sending plain links")
            return {}
        out: dict[int, dict[str, str]] = {}
        try:
            for item_id, _title, url in items:
                per: dict[str, str] = {}
                for action in _ACTIONS:
                    tok = secrets.token_urlsafe(16)
                    table.upsert_entity(
                        {"PartitionKey": "tok", "RowKey": tok, "lens": lens,
                         "itemId": int(item_id), "action": action, "url": url,
                         "ts": int(time.time())},
                        mode=UpdateMode.REPLACE,
                    )
                    per[action] = tok
                out[item_id] = per
        except Exception as e:  # noqa: BLE001
            print(f"deliver: token minting failed ({e}); sending plain links")
            return {}
        return out

    def drain_events(self) -> list[tuple[int, str, str, float]]:
        """Read all gesture events. Returns [(item_id, lens, row, value)]. Events without a `lens`
        field (legacy) are ignored — the loop is fresh, not retro-compatible."""
        if not self.enabled:
            return []
        table = self._table("feedbackevents")
        out: list[tuple[int, str, str, float]] = []
        for e in table.list_entities():
            try:
                lens = str(e.get("lens", ""))
                row = _ACTION_TO_ROW.get(str(e.get("action", "")))
                if not lens or row is None:
                    continue
                out.append((int(e["PartitionKey"]), lens, row, float(e["value"])))
            except (KeyError, ValueError, TypeError):
                continue
        return out

    def record_votes(self, lens: str, item_ids: list[int], value: float) -> int:
        """Write one vote event per item (the same path a human click takes), so feedback_ingest
        reconciles them into affinity:<lens>. value>0 = 👍, <0 = 👎. Returns count; never raises."""
        if not self.enabled or not item_ids or not lens:
            return 0
        action = "up" if value > 0 else "down"
        try:
            from azure.data.tables import UpdateMode
            table = self._table("feedbackevents")
            now = int(time.time())
            for item_id in item_ids:
                table.upsert_entity(
                    {"PartitionKey": str(item_id), "RowKey": f"{lens}:vote", "lens": lens,
                     "value": float(value), "action": action, "ts": now},
                    mode=UpdateMode.REPLACE,
                )
        except Exception as e:  # noqa: BLE001
            print(f"votes: write failed ({e})")
            return 0
        return len(item_ids)
