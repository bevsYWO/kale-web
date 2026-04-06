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
    Uses batched writes to avoid per-row HTTP requests.
    """
    if not is_configured():
        return 0, 0

    sb        = get_client()
    today     = _today()
    email_col = _email_col(df)
    if not email_col:
        return 0, 0

    # Build valid rows
    client_rows = []
    emails_seen = []
    for _, row in df.iterrows():
        email = str(row[email_col]).strip().lower()
        if not email or "@" not in email:
            continue
        row_data = {k: str(v) for k, v in row.items()}
        client_rows.append({
            "email":       email,
            "client":      client_name,
            "date_added":  today,
            "source_file": source_file,
            "row_data":    row_data,
        })
        emails_seen.append(email)

    if not client_rows:
        return 0, len(df)

    skipped = 0

    # Batch upsert client_contacts — one request for the whole file
    try:
        sb.table("client_contacts").upsert(
            client_rows, on_conflict="email,client"
        ).execute()
    except Exception:
        skipped += len(client_rows)
        return 0, skipped

    # Fetch all existing master_contacts for these emails — one request
    try:
        existing_result = (
            sb.table("master_contacts")
            .select("id,email,clients,source_files")
            .in_("email", emails_seen)
            .execute()
        )
        existing_map = {
            r["email"]: r for r in (existing_result.data or [])
        }
    except Exception:
        return 0, skipped

    # Compute updates and inserts in memory
    to_update = []
    to_insert = []
    for email in emails_seen:
        if email in existing_map:
            rec     = existing_map[email]
            clients = list(set((rec.get("clients") or []) + [client_name]))
            sources = list(set((rec.get("source_files") or []) + [source_file]))
            to_update.append({
                "id":           rec["id"],
                "clients":      clients,
                "last_seen":    today,
                "source_files": sources,
            })
        else:
            to_insert.append({
                "email":        email,
                "clients":      [client_name],
                "first_seen":   today,
                "last_seen":    today,
                "source_files": [source_file],
            })

    # Batch upsert master_contacts — one or two requests total
    try:
        if to_insert:
            sb.table("master_contacts").upsert(
                to_insert, on_conflict="email"
            ).execute()
        if to_update:
            sb.table("master_contacts").upsert(
                to_update, on_conflict="id"
            ).execute()
    except Exception as e:
        skipped += len(to_update) + len(to_insert)

    added = len(emails_seen) - skipped
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
