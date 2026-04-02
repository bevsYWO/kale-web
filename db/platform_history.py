"""
db/platform_history.py — Track which platform each email was exported to.

Table: platform_history (email, platform, exported_at)
Unique index on (lower(email), platform).
"""

from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from db.client import get_client, is_configured


def get_platforms_for_emails(emails: list[str]) -> dict[str, list[str]]:
    """
    Returns {email: [platform1, platform2, ...]} for each email in the list.
    Emails with no history are omitted.
    """
    if not is_configured() or not emails:
        return {}
    try:
        sb     = get_client()
        lower  = [e.lower() for e in emails if e]
        result = (
            sb.table("platform_history")
            .select("email,platform")
            .in_("email", lower)
            .execute()
        )
        out: dict[str, list[str]] = {}
        for row in result.data or []:
            e = row["email"]
            p = row["platform"]
            out.setdefault(e, []).append(p)
        return out
    except Exception:
        return {}


def record_export(emails: list[str], platform: str, source_file: str = "") -> None:
    """
    Upsert platform exports for a list of emails.
    Silently ignores errors — export should never be blocked by history tracking.
    """
    if not is_configured() or not emails:
        return
    try:
        sb   = get_client()
        now  = datetime.now(timezone.utc).isoformat()
        rows = [
            {
                "email":       e.lower(),
                "platform":    platform,
                "exported_at": now,
            }
            for e in emails
            if e and "@" in e
        ]
        if rows:
            sb.table("platform_history").upsert(
                rows, on_conflict="email,platform"
            ).execute()
    except Exception:
        pass
