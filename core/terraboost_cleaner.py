"""
core/terraboost_cleaner.py — Section I3 pure-Python logic from kale_data_hub.py.

Validates Terraboost store names, Google star ratings, and business categories.
"""

import re

import pandas as pd

from core.cleaner import _find_col

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
    }


def clean_terraboost_dataframe(df):
    """
    Apply Steps 1-3 to a Terraboost CSV.
    Returns (kept_df, removed_df, col_map).
    """
    df = df.copy()
    for col in df.columns:
        df[col] = df[col].fillna('').astype(str)
    cm = _detect_terraboost_columns(df)

    removed_rows = []   # list of (original_series, reason)
    kept_mask    = [True] * len(df)

    for idx, row in df.iterrows():
        # Step 1 — shop_name must be a valid chain
        if cm['shop_name']:
            canonical = normalize_shop_name(row[cm['shop_name']])
            if canonical is None:
                removed_rows.append(
                    (row, f"Invalid store: {row[cm['shop_name']]!r}"))
                kept_mask[idx] = False
                continue
            df.at[idx, cm['shop_name']] = canonical

        # Step 3 — business_category must not be blank / N/A
        if cm['business_category']:
            bc = str(row[cm['business_category']]).strip()
            if not bc or _TB_PLACEHOLDER_RE.match(bc):
                removed_rows.append((row, "Missing business category"))
                kept_mask[idx] = False
                continue

    # Step 2 — google_stars: clean in place (no row removal)
    kept_df = df[kept_mask].copy()
    if cm['google_stars']:
        kept_df[cm['google_stars']] = kept_df[cm['google_stars']].apply(
            clean_google_stars)

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

    return kept_df, removed_df, cm
