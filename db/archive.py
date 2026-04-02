"""
db/archive.py — Supabase-backed archive operations.

Tables used:
  master_contacts  — one row per unique email
  client_contacts  — full row data per contact per client
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import pandas as pd
import streamlit as st

from db.client import get_client, is_configured


# ==============================================================================
# HELPERS
# ==============================================================================

def _email_col(df: pd.DataFrame) -> Optional[str]:
    """Find the email column in a dataframe (case-insensitive)."""
    import re
    for col in df.columns:
        if re.search(r'^email$|^email[\s_]?address$', col, re.IGNORECASE):
            return col
    return None


def _today() -> str:
    return date.today().isoformat()


# ==============================================================================
# APPEND TO ARCHIVE
# ==============================================================================

def append_to_archive(
    df: pd.DataFrame,
    client_name: str,
    source_file: str,
) -> tuple[int, int]:
    """
    Upsert contacts from df into master_contacts and client_contacts.
    Returns (added, skipped).
    """
    if not is_configured():
        return 0, 0

    sb = get_client()
    today = _today()
    email_col = _email_col(df)
    if not email_col:
        return 0, 0

    added   = 0
    skipped = 0

    for _, row in df.iterrows():
        email = str(row[email_col]).strip().lower()
        if not email or '@' not in email:
            skipped += 1
            continue

        row_data = {k: str(v) for k, v in row.items()}

        # Upsert into client_contacts (unique on lower(email) + client)
        try:
            sb.table("client_contacts").upsert(
                {
                    "email":       email,
                    "client":      client_name,
                    "date_added":  today,
                    "source_file": source_file,
                    "row_data":    row_data,
                },
                on_conflict="email,client",
            ).execute()
        except Exception:
            skipped += 1
            continue

        # Upsert into master_contacts
        try:
            existing = (
                sb.table("master_contacts")
                .select("id,clients,source_files")
                .eq("email", email)
                .execute()
            )
            if existing.data:
                rec      = existing.data[0]
                clients  = list(set(rec.get("clients", []) + [client_name]))
                sources  = list(set(rec.get("source_files", []) + [source_file]))
                sb.table("master_contacts").update(
                    {
                        "clients":      clients,
                        "last_seen":    today,
                        "source_files": sources,
                    }
                ).eq("id", rec["id"]).execute()
            else:
                sb.table("master_contacts").insert(
                    {
                        "email":        email,
                        "clients":      [client_name],
                        "first_seen":   today,
                        "last_seen":    today,
                        "source_files": [source_file],
                    }
                ).execute()
            added += 1
        except Exception:
            skipped += 1

    return added, skipped


# ==============================================================================
# LOAD ARCHIVE
# ==============================================================================

@st.cache_data(ttl=300)
def load_archive(
    client_filter: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> pd.DataFrame:
    """
    Query master_contacts with optional filters.
    Returns a pandas DataFrame.
    """
    if not is_configured():
        return pd.DataFrame(columns=["email", "clients", "first_seen", "last_seen", "source_files"])

    try:
        sb = get_client()
        query = sb.table("master_contacts").select("*")

        if date_from:
            query = query.gte("first_seen", date_from)
        if date_to:
            query = query.lte("first_seen", date_to)

        result = query.execute()
        rows   = result.data or []
        df     = pd.DataFrame(rows)

        if df.empty:
            return df

        # client_filter: keep rows where clients array contains client_name
        if client_filter and client_filter != "All":
            df = df[df["clients"].apply(
                lambda c: client_filter in (c if isinstance(c, list) else [])
            )]

        # search: filter by email substring
        if search:
            df = df[df["email"].str.contains(search, case=False, na=False)]

        return df.reset_index(drop=True)

    except Exception as e:
        st.warning(f"Archive load error: {e}")
        return pd.DataFrame()


# ==============================================================================
# GET CLIENT COUNTS
# ==============================================================================

@st.cache_data(ttl=300)
def get_client_counts() -> dict:
    """Count contacts per client from master_contacts."""
    if not is_configured():
        return {}
    try:
        sb     = get_client()
        result = sb.table("master_contacts").select("clients").execute()
        counts: dict[str, int] = {}
        for row in result.data or []:
            for c in (row.get("clients") or []):
                counts[c] = counts.get(c, 0) + 1
        return counts
    except Exception:
        return {}


# ==============================================================================
# CHECK DUPES
# ==============================================================================

def check_dupes(emails: list[str], client_name: str) -> dict[str, list[str]]:
    """
    Return {email: [clients where seen]} for each email in the list.
    Only returns emails that already exist in master_contacts.
    """
    if not is_configured() or not emails:
        return {}
    try:
        sb      = get_client()
        lower   = [e.lower() for e in emails if e]
        result  = (
            sb.table("master_contacts")
            .select("email,clients")
            .in_("email", lower)
            .execute()
        )
        return {
            row["email"]: row.get("clients", [])
            for row in (result.data or [])
        }
    except Exception:
        return {}
