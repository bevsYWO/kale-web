"""
db/archive.py — Supabase-backed archive operations.

Tables used:
  master_contacts  — one row per unique email
  client_contacts  — full row data per contact per client
"""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Optional

import pandas as pd
import streamlit as st

from db.client import get_client, is_configured


def _retry(fn, retries=3, delay=2):
    """Call fn(), retrying up to `retries` times on failure with a delay."""
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(delay)
            else:
                raise


# ==============================================================================
# HELPERS
# ==============================================================================

def _email_col(df: pd.DataFrame) -> Optional[str]:
    """Find the email column in a dataframe (case-insensitive)."""
    import re
    for col in df.columns:
        if re.search(r'email', col, re.IGNORECASE):
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

    # Build valid rows — deduplicate by email to avoid upsert conflicts
    seen_set    = set()
    client_rows = []
    emails_seen = []
    for _, row in df.iterrows():
        email = str(row[email_col]).strip().lower()
        if not email or "@" not in email or email in seen_set:
            continue
        seen_set.add(email)
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

    CHUNK = 200  # safe limit to stay under Supabase URL length cap

    # Batch upsert client_contacts in chunks
    for i in range(0, len(client_rows), CHUNK):
        chunk = client_rows[i:i + CHUNK]
        _retry(lambda c=chunk: sb.table("client_contacts").upsert(
            c, on_conflict="email,client"
        ).execute())

    # Fetch existing master_contacts in chunks to avoid URL length limit
    existing_map: dict = {}
    for i in range(0, len(emails_seen), CHUNK):
        chunk = emails_seen[i:i + CHUNK]
        result = _retry(lambda c=chunk: sb.table("master_contacts")
            .select("id,email,clients,source_files")
            .in_("email", c)
            .execute())
        for r in (result.data or []):
            existing_map[r["email"]] = r

    # Compute upsert rows in memory (no id — email is the conflict key)
    to_upsert = []
    for email in emails_seen:
        if email in existing_map:
            rec     = existing_map[email]
            clients = list(set((rec.get("clients") or []) + [client_name]))
            sources = list(set((rec.get("source_files") or []) + [source_file]))
            to_upsert.append({
                "email":        email,
                "clients":      clients,
                "last_seen":    today,
                "source_files": sources,
            })
        else:
            to_upsert.append({
                "email":        email,
                "clients":      [client_name],
                "first_seen":   today,
                "last_seen":    today,
                "source_files": [source_file],
            })

    # Batch upsert master_contacts in chunks
    for i in range(0, len(to_upsert), CHUNK):
        chunk = to_upsert[i:i + CHUNK]
        _retry(lambda c=chunk: sb.table("master_contacts").upsert(
            c, on_conflict="email"
        ).execute())

    added   = len(emails_seen)
    skipped = len(df) - added
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
        sb    = get_client()
        PAGE  = 1000
        rows  = []
        start = 0
        while True:
            query = sb.table("master_contacts").select("*").range(start, start + PAGE - 1)
            if date_from:
                query = query.gte("first_seen", date_from)
            if date_to:
                query = query.lte("first_seen", date_to)
            batch = query.execute().data or []
            rows.extend(batch)
            if len(batch) < PAGE:
                break
            start += PAGE

        df = pd.DataFrame(rows)

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
def get_total_contact_count() -> int:
    """Return total unique contacts in master_contacts (exact COUNT query)."""
    if not is_configured():
        return 0
    try:
        sb     = get_client()
        result = sb.table("master_contacts").select("*", count="exact").limit(0).execute()
        return result.count or 0
    except Exception:
        return 0


@st.cache_data(ttl=300)
def get_client_counts() -> dict:
    """Count contacts per client from master_contacts (paginated)."""
    if not is_configured():
        return {}
    try:
        sb     = get_client()
        PAGE   = 1000
        counts: dict[str, int] = {}
        start  = 0
        while True:
            batch = (
                sb.table("master_contacts")
                .select("clients")
                .range(start, start + PAGE - 1)
                .execute()
                .data or []
            )
            for row in batch:
                for c in (row.get("clients") or []):
                    counts[c] = counts.get(c, 0) + 1
            if len(batch) < PAGE:
                break
            start += PAGE
        return counts
    except Exception:
        return {}


# ==============================================================================
# CHECK DUPES
# ==============================================================================

def check_dupes(emails: list[str], client_name: str) -> dict[str, list[str]]:
    """
    Return {email: [clients where seen]} for each email already in master_contacts.
    Batched to avoid Supabase URL length limits on large lists.
    Call this BEFORE append_to_archive so new contacts aren't treated as dupes.
    """
    if not is_configured() or not emails:
        return {}
    try:
        sb     = get_client()
        lower  = [e.lower() for e in emails if e]
        CHUNK  = 200
        result_map: dict[str, list[str]] = {}
        for i in range(0, len(lower), CHUNK):
            chunk = lower[i:i + CHUNK]
            rows  = (
                sb.table("master_contacts")
                .select("email,clients")
                .in_("email", chunk)
                .execute()
                .data or []
            )
            for row in rows:
                result_map[row["email"]] = row.get("clients", [])
        return result_map
    except Exception:
        return {}
