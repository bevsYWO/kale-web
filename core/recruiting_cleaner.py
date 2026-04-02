"""
core/recruiting_cleaner.py — Section I2 pure-Python logic from kale_data_hub.py.

N2 Recruiting-specific cleaning: first name, first line (company), city.
"""

import re

from core.cleaner import (
    clean_cell,
    fix_company_slash,
    fix_first_name,
    _STREET_SUFFIX_RE,
    _POSTAL_CODE_RE,
    _find_col,
)

# ==============================================================================
# CONSTANTS
# ==============================================================================

# Mojibake artifacts seen specifically in N2 Recruiting first_line data
_N2R_EXTRA_STRIP = str.maketrans({
    '\u221a': '',   # sqrt  square root sign — mojibake artifact
    '\u00a2': '',   # cent sign              — mojibake artifact
})

_N2R_PLACEHOLDER_RE = re.compile(
    r'^(n/?a\.?|none|unknown|--|-)$', re.IGNORECASE
)

# US zip: 5 digits, or 5+4 with hyphen
_US_ZIP_RE = re.compile(r'\b\d{5}(?:-\d{4})?\b')

# Try to load pgeocode for zip -> city lookups (optional dependency)
try:
    import pgeocode as _pgeocode
    _NOMI_US = _pgeocode.Nominatim('us')
    def _zip_to_city(zipcode):
        z = re.sub(r'\D', '', str(zipcode))[:5]
        if len(z) == 5:
            try:
                result = _NOMI_US.query_postal_code(z)
                city = result.place_name
                if city and str(city) != 'nan':
                    return str(city).strip()
            except Exception:
                pass
        return ''
except Exception:
    def _zip_to_city(_):
        return ''

# Regex to pull "City, ST" out of a full US address string
_CITY_FROM_ADDR_RE = re.compile(
    r',\s*([A-Za-z][A-Za-z\s\-\.]{1,30}?)\s*,\s*[A-Z]{2}\b'
)


# ==============================================================================
# CITY HELPERS
# ==============================================================================

def _city_from_address(address):
    """Extract city name from a full address string like '123 Main St, Austin, TX 78701'."""
    m = _CITY_FROM_ADDR_RE.search(str(address))
    if m:
        city = m.group(1).strip()
        if city and not re.search(r'\d', city) and not _STREET_SUFFIX_RE.search(city):
            return city.title()
    return ''


def fix_recruiting_city(value):
    """Return a valid, properly-cased city string, or '' for addresses/zips/blanks/N/A."""
    v = str(value).strip()
    if not v or _N2R_PLACEHOLDER_RE.match(v):
        return ''
    if _US_ZIP_RE.search(v) or _POSTAL_CODE_RE.search(v):
        return ''
    if re.search(r'\d', v):
        return ''
    if _STREET_SUFFIX_RE.search(v):
        return ''
    return v.title()


def fix_recruiting_city_from_row(city_val, zip_val='', address_val=''):
    """
    Return a valid city string.
    If city_val is invalid, infer from address (fast) then zip (pgeocode).
    """
    city = fix_recruiting_city(city_val)
    if city:
        return city
    if address_val:
        inferred = _city_from_address(address_val)
        if inferred:
            return inferred
    if zip_val:
        inferred = _zip_to_city(zip_val)
        if inferred:
            return inferred
    return ''


# ==============================================================================
# FIRST LINE (COMPANY) HELPER
# ==============================================================================

def fix_recruiting_firstline(text, website=''):
    """
    Clean a First Line value for N2 Recruiting:
      - Full cell clean (mojibake, accents, HTML entities, typographic chars)
      - Strips sqrt and cent artifacts
      - Resolves bilingual/slash company names (uses website domain as hint)
      - Blank / N/A -> empty string
    """
    text = str(text).strip()
    if not text or _N2R_PLACEHOLDER_RE.match(text):
        return ''
    text = clean_cell(text)
    text = text.translate(_N2R_EXTRA_STRIP)
    if not text or _N2R_PLACEHOLDER_RE.match(text):
        return ''
    if '/' in text:
        if website:
            domain = re.sub(r'^https?://(www\.)?', '', str(website).strip().lower())
            domain = re.split(r'[./]', domain)[0]
            if domain and len(domain) > 2:
                parts = [p.strip() for p in text.split('/') if p.strip()]
                if len(parts) == 2:
                    for p in parts:
                        if domain in p.lower() or p.lower().startswith(domain[:4]):
                            text = p
                            break
                    else:
                        text = fix_company_slash(text)
                else:
                    text = fix_company_slash(text)
            else:
                text = fix_company_slash(text)
        else:
            text = fix_company_slash(text)
    text = re.sub(r' {2,}', ' ', text).strip()
    return text


# ==============================================================================
# COLUMN DETECTION
# ==============================================================================

def _detect_recruiting_columns(df):
    cols = list(df.columns)
    return {
        'first_name': _find_col(cols, r'^first[\s_]?name$'),
        'first_line': _find_col(cols, r'^first[\s_]?line$'),
        'city':       _find_col(cols, r'^city$'),
        'zip':        _find_col(cols, r'^zip[\s_]?code$', r'^zip$', r'^postal[\s_]?code$'),
        'address':    _find_col(cols, r'^(street[\s_]?)?address[\s_]?(1|line)?$',
                                     r'^full[\s_]?address$', r'^location$'),
        'website':    _find_col(cols, r'company[\s_]?website[\s_]?full',
                                     r'website[\s_]?full', r'^website$'),
        'email':      _find_col(cols, r'^email$', r'^email[\s_]?address$'),
        'linkedin':   _find_col(cols, r'linkedin', r'profile[\s_]?url'),
    }


# ==============================================================================
# EXPORT COLUMN RENAME MAP
# ==============================================================================

N2R_EXPORT_RENAME = {
    'first_name': 'first Name',
    'first_line': 'first_line',
    'city':       'City',
}


# ==============================================================================
# MAIN CLEANER
# ==============================================================================

def clean_recruiting_dataframe(df):
    """Apply Steps 1-3 to a recruiting CSV. Returns (cleaned_df, col_map)."""
    df = df.copy()
    for col in df.columns:
        df[col] = df[col].fillna('').astype(str)
    cm = _detect_recruiting_columns(df)

    # Step 1 — First Name
    if cm['first_name']:
        df[cm['first_name']] = df.apply(
            lambda r: fix_first_name(
                r[cm['first_name']],
                r[cm['email']]    if cm['email']    else '',
                r[cm['linkedin']] if cm['linkedin'] else '',
            ), axis=1)

    # Step 2 — First Line
    if cm['first_line']:
        if cm['website']:
            df[cm['first_line']] = df.apply(
                lambda r: fix_recruiting_firstline(
                    r[cm['first_line']], r[cm['website']]), axis=1)
        else:
            df[cm['first_line']] = df[cm['first_line']].apply(
                fix_recruiting_firstline)

    # Step 3 — City (invalid values inferred from address / zip where possible)
    if cm['city']:
        df[cm['city']] = df.apply(
            lambda r: fix_recruiting_city_from_row(
                r[cm['city']],
                r[cm['zip']]     if cm.get('zip')     else '',
                r[cm['address']] if cm.get('address') else '',
            ), axis=1)

    for col in df.columns:
        df[col] = df[col].apply(lambda x: re.sub(r' {2,}', ' ', str(x)).strip())

    return df, cm
