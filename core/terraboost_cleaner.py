"""
core/terraboost_cleaner.py — Section I3 pure-Python logic from kale_data_hub.py.

Validates Terraboost store names, Google star ratings, and business categories.
"""

import re

import pandas as pd

from core.cleaner import _find_col, _fix_name_encoding

# ==============================================================================
# CONSTANTS
# ==============================================================================

# Valid grocery chains for shop_name (Step 1)
_TB_VALID_CHAINS = [
    ("Harris Teeter", re.compile(r'harris[\s\-]?teeter', re.IGNORECASE)),
    ("HEB",           re.compile(r'h[\s\-]?e[\s\-]?b',  re.IGNORECASE)),
    ("Kroger",        re.compile(r'\bkroger\b',          re.IGNORECASE)),
    ("Jewel",         re.compile(r'\bjewel\b',           re.IGNORECASE)),
    ("Albertsons",    re.compile(r'\balbertsons?\b',     re.IGNORECASE)),
]

_TB_PLACEHOLDER_RE = re.compile(
    r'^(n/?a\.?|none|unknown|--|-)$', re.IGNORECASE
)

# Characters not typical in company names (kept: word chars, spaces, . , & ' - ( ) / + # @)
_TB_SPECIAL_CHAR_RE = re.compile(r'[^\w\s\.\,\&\'\-\(\)\/\+\#\@]', re.UNICODE)

# Step 4 — canonical output column names
TB_EXPORT_RENAME = {
    'shop_name':         'shop_name',
    'google_stars':      'googlestars',
    'business_category': 'Business category',
}


# ==============================================================================
# CLEANING FUNCTIONS
# ==============================================================================

def normalize_shop_name(value):
    """Return the canonical chain name if value matches a valid chain, else None."""
    v = str(value).strip()
    if not v or _TB_PLACEHOLDER_RE.match(v):
        return None
    for canonical, pattern in _TB_VALID_CHAINS:
        if pattern.search(v):
            return canonical
    return None


def clean_company_name(value):
    """
    Clean a company name:
    - Fix mojibake encoding (Ã© → é)
    - Strip accents to plain ASCII (é → e, ñ → n)
    - Remove control/non-printable characters
    - Replace stray special characters with a space
    - Collapse extra whitespace
    Returns cleaned string, or None if the result is blank/garbled.
    """
    v = _fix_name_encoding(str(value))  # mojibake fix + accent strip → plain ASCII
    if not v or _TB_PLACEHOLDER_RE.match(v):
        return None
    # Replace special characters not typical in company names
    v = _TB_SPECIAL_CHAR_RE.sub(' ', v)
    # Collapse extra whitespace
    v = re.sub(r' {2,}', ' ', v).strip()
    # Must have at least 2 alphanumeric characters to be a valid name
    if not v or sum(1 for c in v if c.isalnum()) < 2:
        return None
    return v


def clean_google_stars(value):
    """Return a clean star string (numeric 1.0-5.0), or '' for blank/invalid."""
    v = str(value).strip()
    if not v or _TB_PLACEHOLDER_RE.match(v):
        return ''
    try:
        f = float(v)
        if 1.0 <= f <= 5.0:
            return v.strip()
        return ''
    except ValueError:
        return ''


def _detect_terraboost_columns(df):
    cols = list(df.columns)
    return {
        'shop_name':         _find_col(cols, r'shop[\s_]?name', r'store[\s_]?name'),
        'google_stars':      _find_col(cols, r'google[\s_]?stars?', r'star[\s_]?rating',
                                            r'^stars?$', r'^rating$'),
        'business_category': _find_col(cols, r'business[\s_]?categor', r'^categor'),
        'company_name':      _find_col(cols, r'cleaned[\s_]?company[\s_]?name',
                                            r'company[\s_]?name'),
    }


def clean_terraboost_dataframe(df):
    """
    Apply Steps 1-4 to a Terraboost CSV.
    Returns (kept_df, removed_df, changed_df, col_map).
    changed_df contains kept rows that had values modified in place,
    with a '_changes' column describing what was altered.
    """
    df = df.copy()
    for col in df.columns:
        df[col] = df[col].fillna('').astype(str)
    cm = _detect_terraboost_columns(df)

    removed_rows = []           # list of (original_series, reason)
    kept_mask    = [True] * len(df)
    change_log   = {}           # idx -> list of change description strings

    for idx, row in df.iterrows():
        row_changes = []

        # Step 1 — shop_name must be a valid chain
        if cm['shop_name']:
            canonical = normalize_shop_name(row[cm['shop_name']])
            if canonical is None:
                removed_rows.append(
                    (row, f"Invalid store: {row[cm['shop_name']]!r}"))
                kept_mask[idx] = False
                continue
            if canonical != row[cm['shop_name']]:
                row_changes.append(f"Store name: {row[cm['shop_name']]!r} → {canonical!r}")
            df.at[idx, cm['shop_name']] = canonical

        # Step 3 — business_category must not be blank / N/A
        if cm['business_category']:
            bc = str(row[cm['business_category']]).strip()
            if not bc or _TB_PLACEHOLDER_RE.match(bc):
                removed_rows.append((row, "Missing business category"))
                kept_mask[idx] = False
                continue

        # Step 4 — company_name: fix encoding/accents, clean special chars; remove if garbled
        if cm['company_name']:
            orig_cn = row[cm['company_name']]
            cn = clean_company_name(orig_cn)
            if cn is None:
                removed_rows.append(
                    (row, f"Garbled/invalid company name: {orig_cn!r}"))
                kept_mask[idx] = False
                continue
            if cn != orig_cn:
                row_changes.append(f"Company name: {orig_cn!r} → {cn!r}")
            df.at[idx, cm['company_name']] = cn

        if row_changes:
            change_log[idx] = row_changes

    # Step 2 — google_stars: clean in place (no row removal), track changes
    kept_df = df[kept_mask].copy()
    if cm['google_stars']:
        orig_stars_col = kept_df[cm['google_stars']].copy()
        kept_df[cm['google_stars']] = kept_df[cm['google_stars']].apply(clean_google_stars)
        for idx2 in kept_df.index:
            if kept_df.at[idx2, cm['google_stars']] != orig_stars_col.at[idx2]:
                change_log.setdefault(idx2, []).append(
                    f"Stars: {orig_stars_col.at[idx2]!r} → {kept_df.at[idx2, cm['google_stars']]!r}")

    # Build removed dataframe
    if removed_rows:
        removed_df = pd.DataFrame([r for r, _ in removed_rows],
                                  columns=df.columns)
        removed_df['_removal_reason'] = [reason for _, reason in removed_rows]
    else:
        removed_df = pd.DataFrame(columns=list(df.columns) + ['_removal_reason'])

    # Tidy whitespace on kept rows
    for col in kept_df.columns:
        kept_df[col] = kept_df[col].apply(
            lambda x: re.sub(r' {2,}', ' ', str(x)).strip())

    # Build changed dataframe (subset of kept rows that had in-place edits)
    changed_indices = [idx for idx in kept_df.index if idx in change_log]
    if changed_indices:
        changed_df = kept_df.loc[changed_indices].copy()
        changed_df.insert(0, '_changes', ['; '.join(change_log[i]) for i in changed_indices])
    else:
        changed_df = pd.DataFrame(columns=['_changes'] + list(kept_df.columns))

    return kept_df, removed_df, changed_df, cm
