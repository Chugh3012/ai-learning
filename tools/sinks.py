#!/usr/bin/env python3
"""Delivery SINKS + the run orchestrator (ports & adapters).

Each output channel is a Sink adapter behind one interface; the orchestrator selects each
profile's items through the shared filter (tools/selection.py) and hands them to the profile's
sink. Adding a channel — or a future autonomous publisher — is a new Sink subclass + one registry
row, with NO change to selection, ranking, or the orchestrator.

The orchestrator drives the CADENCE: the scheduled pass honors each profile's cadence and skips
on-demand profiles; a manual pass (`--produce <user>:<profile>`) runs exactly the requested
lenses, bypassing cadence.
"""
from __future__ import annotations

import sqlite3
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import notify
from profiles import User
from selection import select_items, mark_sent, _interest_weight


@dataclass
class DeliveryContext:
    """Everything a sink needs to deliver one profile's already-selected items."""
    con: sqlite3.Connection
    env: dict
    endpoint: str          # Foundry project endpoint
    model: str             # chat deployment
    profile: "object"      # profiles.Profile (avoid import cycle in the annotation)
    selected: list[dict]


class Sink(ABC):
    """One output channel. `explore_ratio` None => use the config default during selection; a
    content/production sink overrides to 0.0 (deterministic — never gamble a production slot on a
    wildcard)."""
    explore_ratio: float | None = None

    @abstractmethod
    def deliver(self, ctx: DeliveryContext) -> bool:
        """Emit the selected items. Return True on success (so the orchestrator marks them sent)."""
        raise NotImplementedError


class DeliverySink(Sink):
    """Shared base for the human-facing reading channels (email, digest): build the learning
    brief, mint feedback tokens, render once, then emit through the concrete channel."""

    def deliver(self, ctx: DeliveryContext) -> bool:
        p = ctx.profile
        rows = [(d["id"], d["title"], d["url"]) for d in ctx.selected]
        blurb = [(d["id"], d["title"], notify._fulltext(d["url"]) or d["summary"])
                 for d in ctx.selected]
        theme, cards = notify._lessons(ctx.endpoint, ctx.model, blurb)
        connections = notify._connections(ctx.con, p.lens, ctx.selected)
        feedback_url = ctx.env.get("FEEDBACK_URL", "")
        account = ctx.env.get("FEEDBACK_STORAGE", "")
        tokens = notify._mint_tokens(account, p.lens, rows) if feedback_url else {}
        plain, body_html = notify._render(rows, theme, cards, connections, feedback_url, tokens)
        return self._emit(ctx, plain, body_html, rows)

    @abstractmethod
    def _emit(self, ctx: DeliveryContext, plain: str, body_html: str, rows: list[tuple]) -> bool:
        raise NotImplementedError


class EmailSink(DeliverySink):
    def _emit(self, ctx: DeliveryContext, plain: str, body_html: str, rows: list[tuple]) -> bool:
        p = ctx.profile
        to = ctx.env.get(p.email_var or "EMAIL_TO", "")
        subject = f"ai-scout \u2014 {len(rows)} new ways to use AI"
        return notify.send_email(ctx.env.get("ACS_ENDPOINT", ""), ctx.env.get("EMAIL_SENDER", ""),
                                 to, subject, plain, body_html)


class DigestSink(DeliverySink):
    def _emit(self, ctx: DeliveryContext, plain: str, body_html: str, rows: list[tuple]) -> bool:
        p = ctx.profile
        return notify.write_digest(p.filesafe_lens, p.label, len(rows), plain, [r[0] for r in rows])


class DraftSink(Sink):
    """On-demand content sink: produce a kit per selected item via the profile's content FORMAT.
    Deterministic selection (no explore wildcard on a production slot)."""
    explore_ratio = 0.0

    def deliver(self, ctx: DeliveryContext) -> bool:
        from draft import produce
        return produce(ctx.con, ctx.endpoint, ctx.model, ctx.profile, ctx.selected) > 0


_SINKS: dict[str, type[Sink]] = {"email": EmailSink, "digest": DigestSink, "draft": DraftSink}


def make_sink(channel: str) -> Sink:
    """Factory: resolve a channel name to its Sink adapter."""
    cls = _SINKS.get(channel)
    if cls is None:
        raise ValueError(f"unknown delivery channel '{channel}'")
    return cls()


def _last_sent_ts(con: sqlite3.Connection, lens: str) -> int | None:
    row = con.execute("SELECT MAX(ts) FROM signal WHERE kind=?", (f"sent:{lens}",)).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def deliver_all(con: sqlite3.Connection, users: list[User], env: dict, endpoint: str, model: str,
                targets: set[str] | None = None) -> int:
    """Run delivery across every profile of every user from the ONE shared ranking.
    targets=None => the SCHEDULED pass: skip on-demand profiles and honor each cadence.
    targets set (of `<user_id>:<profile_id>` lenses) => a MANUAL pass: run exactly those,
    bypassing cadence. Each profile personalizes the shared ranking by its own interest match +
    feedback affinity, gated by min_score (a quiet run delivers nothing). Returns total delivered."""
    from embed import embed_interest
    embed_model = env.get("FOUNDRY_EMBED_NAME", "embed")
    interest_weight = _interest_weight()
    now = int(time.time())
    total = 0
    for user in users:
        for p in user.profiles:
            if targets is not None:
                if p.lens not in targets:
                    continue
            elif not p.cadence.is_due(_last_sent_ts(con, p.lens), now):
                continue
            sink = make_sink(p.channel)
            interest_vec = embed_interest(endpoint, embed_model, p.interest)
            selected = select_items(con, p.lens, p.top, p.min_score, interest_vec,
                                    interest_weight, sink.explore_ratio)
            if not selected:
                print(f"deliver: nothing clears {p.lens} (min_score={p.min_score:g}) — quiet")
                continue
            ctx = DeliveryContext(con, env, endpoint, model, p, selected)
            if sink.deliver(ctx):
                mark_sent(con, p.lens, [d["id"] for d in selected])
                total += len(selected)
                print(f"deliver: {len(selected)} -> {p.lens} ({p.channel})")
    return total
