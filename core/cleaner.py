"""
core/cleaner.py — Section A logic from kale_data_hub.py (pure Python, no Streamlit).

Includes all cleaning functions: clean_cell, clean_dataframe, fix_* helpers,
detect_change_type, compute_diff, build_summary, build_hotspots.
"""

import html
import re
import unicodedata
from collections import defaultdict


# ==============================================================================
# LOW-LEVEL TEXT FIXERS
# ==============================================================================

def _fix_ctrl_digit(text):
    return re.sub(r'[\x16\x17]\d', 'e', text)

def _remove_control_chars(text):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

def _fix_mojibake(text):
    try:
        return text.encode('latin-1').decode('utf-8')
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text

def _fix_name_encoding(text):
    """Fix encoding in a name: decode mojibake then strip to plain ASCII letters (Ã© → é → e)."""
    text = _fix_ctrl_digit(text)
    text = _remove_control_chars(text)
    text = _fix_mojibake(text)   # Ã© → é  (mojibake: latin-1 bytes read as UTF-8 chars)
    text = _strip_accents(text)  # é → e, ü → u, ñ → n, etc.
    text = _decode_html(text)    # &eacute; → e (after strip_accents handles any remaining)
    text = _fix_typographic(text)
    return text.strip()

# Detects still-garbled sequences that survive the mojibake fix attempt
_GARBLED_RE = re.compile(r'Ã[^\s]|Â[^\s]|â€')

def _name_from_email(email):
    """Extract a candidate first name from an email prefix (e.g. john.doe@ → John)."""
    if not email or '@' not in email:
        return ''
    prefix = email.split('@')[0]
    prefix = re.sub(r'\d+$', '', prefix)
    parts = re.split(r'[._\-+]', prefix)
    parts = [p for p in parts if len(p) >= 2 and re.match(r'^[A-Za-z]+$', p)]
    if parts:
        return parts[0].capitalize()
    return ''

def _strip_accents(text):
    nfd = unicodedata.normalize('NFD', text)
    return ''.join(c for c in nfd if unicodedata.category(c) != 'Mn')

def _decode_html(text):
    return html.unescape(text)

_TYPOGRAPHIC = str.maketrans({
    '\u2018': "'",  '\u2019': "'",
    '\u201c': '"',  '\u201d': '"',
    '\u2013': '-',  '\u2014': '-',
    '\u2026': '....',
    '\u2022': '-',  '\u25ba': '-',
    '\u00b7': '.',
    '\u200b': '',   '\u200c': '',   '\u200d': '',
    '\u2122': '',   '\u00ae': '',   '\u00a9': '',
    '\ufeff': '',
})

def _fix_typographic(text):
    return text.translate(_TYPOGRAPHIC)

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001F926-\U0001F937"
    "\U00010000-\U0010FFFF"
    "\u2640-\u2642"
    "\u2600-\u2B55"
    "\u23CF\u23E9\u231A\uFE0F\u3030"
    "]+",
    re.UNICODE,
)

_CJK_RE = re.compile(
    "["
    "\u4E00-\u9FFF"
    "\u3400-\u4DBF"
    "\u3000-\u303F"
    "\uFF00-\uFFEF"
    "\u3040-\u309F"
    "\u30A0-\u30FF"
    "]+"
)

def _remove_symbols(text):
    text = _EMOJI_RE.sub('', text)
    text = _CJK_RE.sub('', text)
    return text

def _remove_checkmark(text):
    return re.sub(r'^[\u2705\u2714]\s*', '', text.strip())

_EXCEL_ERROR_RE = re.compile(
    r'#(?:NAME|VALUE|REF|N/A|DIV/0!|NUM|NULL)\??\s*', re.IGNORECASE
)

def _remove_excel_errors(text):
    return _EXCEL_ERROR_RE.sub('', text).strip()


# ==============================================================================
# MAIN CELL CLEANER
# ==============================================================================

def clean_cell(value):
    if value is None:
        return ''
    text = str(value)
    text = _fix_ctrl_digit(text)
    text = _remove_control_chars(text)
    text = _fix_mojibake(text)
    text = _strip_accents(text)
    text = _decode_html(text)
    text = _fix_typographic(text)
    text = _remove_symbols(text)
    text = text.replace('::', ' - ')
    text = _remove_checkmark(text)
    text = _remove_excel_errors(text)
    return text.strip()


# ==============================================================================
# DOMAIN-SPECIFIC FIXERS
# ==============================================================================

_STREET_SUFFIX_RE = re.compile(
    r'\b(floor|unit|suite|ste|rd|ave|blvd|street|avenue|road|hwy|dr|drive|'
    r'lane|ln|way|ct|crescent)\b',
    re.IGNORECASE,
)
_POSTAL_CODE_RE = re.compile(r'\b[A-Za-z]\s*\d\s*[A-Za-z]\s*\d\s*[A-Za-z]\s*\d\b')

_METRO_RE = re.compile(
    r'^\s*greater\s+(.+?)\s+(?:metropolitan\s+area|metro\s+area|area)\s*$'
    r'|^(.+?)\s+(?:metropolitan\s+area|metro\s+area)\s*$',
    re.IGNORECASE,
)

_ADMIN_SUFFIX_RE = re.compile(
    r'^(.+?)\s+(?:regional\s+county\s+municipality'
    r'|regional\s+municipality'
    r'|regional\s+district'
    r'|county\s+municipality'
    r'|township'
    r')\s*$',
    re.IGNORECASE,
)

_ADMIN_PREFIX_RE = re.compile(
    r'^(?:charter\s+)?'
    r'(?:regional\s+county\s+municipality'
    r'|regional\s+municipality'
    r'|regional\s+district'
    r'|township'
    r'|town'
    r'|city'
    r'|municipality'
    r')\s+of\s+(.+)$',
    re.IGNORECASE,
)

def fix_subject_city(value):
    v = value.strip()
    if not v or v.lower() in ('your city', 'Your city'):
        return 'Your city'
    v = v.split(',')[0].strip()
    if not v:
        return 'Your city'
    if re.search(r'\d', v):
        return 'Your city'
    if _STREET_SUFFIX_RE.search(v):
        return 'Your city'
    if _POSTAL_CODE_RE.search(v):
        return 'Your city'
    m = _METRO_RE.match(v)
    if m:
        v = (m.group(1) or m.group(2)).strip()
        v = re.sub(r'\s*\([^)]*\)', '', v).strip()
        return v.title()
    m = _ADMIN_SUFFIX_RE.match(v)
    if m:
        return m.group(1).strip().title()
    m = _ADMIN_PREFIX_RE.match(v)
    if m:
        return m.group(1).strip().title()
    return v.title()

_UNI_CORRECTIONS = {
    'Augustana Faculty, University of Alberta': 'University of Alberta',
}

def _fix_garbled_uni(text):
    text = re.sub(r'(?<=[A-Za-z])3', 'e', text)
    text = re.sub(r'\b3(?=[A-Za-z])', 'E', text)
    return text

def fix_university(uni, local_school=''):
    uni = uni.strip()
    if not uni and local_school:
        uni = local_school.strip()
    uni = _fix_garbled_uni(uni)
    return _UNI_CORRECTIONS.get(uni, uni)

_COMPANY_EXACT = {
    'AquaEye / VodaSafe':                                        'VodaSafe',
    'AquaEye/VodaSafe':                                          'VodaSafe',
    'Foremost Financial Corporation (Lic # 10342/11654)':        'Foremost Financial Corporation',
    'Mobile Savvy - TELUS/Koodo Authorized Dealer':              'Mobile Savvy',
    'MD/cosmetic and laser clinic':                              'MD Cosmetic and Laser Clinic',
    'GROUPE TFT-ALCO INC./ TFT-ALCO GROUP INC.':                'GROUPE TFT-ALCO INC.',
    'GROUPE TFT-ALCO INC./TFT-ALCO GROUP INC.':                 'GROUPE TFT-ALCO INC.',
    'Forget Smith Barristers/Avocat(e)s':                        'Forget Smith Barristers',
    "United Way Centraide North East Ontario/Nord-est de l'Ontario": 'United Way Centraide North East Ontario',
}

_KEEP_SLASH_RE = re.compile(
    r'(?:'
    r'RE/MAX|20/20|24/7|North/South|HIV/AIDS|Odan/Detech|NS/PEI'
    r'|CASN/ACESI|NISA/Northern|IABC/BC|BMW/MINI|CEWIL/ECAIT'
    r'|\bui/ux\b|\ba/v\b|\bNEW/USED\b|\bof/de\b|Alnwick/[Hh]aldimand'
    r')',
    re.IGNORECASE,
)

_LEGAL_SUFFIX_RE = re.compile(
    r'\s*/?\s*'
    r'(?:Lt[eé]e/Ltd|Ltd/Lt[eé]e|srl/LLP|LLP/s\.r\.l\.|s\.e\.n\.c\.r\.l\.|LLP/SRL)'
    r'\s*\.?\s*$',
    re.IGNORECASE,
)

def fix_company_slash(name):
    name = name.strip()
    if '/' not in name:
        return name
    if name in _COMPANY_EXACT:
        return _COMPANY_EXACT[name]
    name_lower = name.lower()
    for wrong, right in _COMPANY_EXACT.items():
        if name_lower == wrong.lower():
            return right
    name = _LEGAL_SUFFIX_RE.sub('', name).strip()
    if '/' not in name:
        return name
    if _KEEP_SLASH_RE.search(name):
        return name
    return name.split('/')[0].strip().rstrip(' -,')

_PLACEHOLDER_NAMES = frozenset({
    'n/a', 'na', 'n.a.', 'none', 'unknown', '-', '--', '.', 'test', 'there',
})
_CONJUNCTIONS_RE = re.compile(
    r'^(and/or|his/her|he/she|him/her|s/he|w/o|w/e)$', re.IGNORECASE
)

def fix_first_name(first, email='', linkedin=''):
    v = _fix_name_encoding(str(first))   # Ã© → é → e (mojibake fix + strip accents to plain ASCII)
    v = re.sub(r"^['\u2018\u2019\"`]+", '', v).strip()
    v = re.sub(r"^~+", '', v).strip()
    if v:
        v = v[0].upper() + v[1:]
    if not v:
        return _name_from_email(email) or 'there'
    lower_v = v.lower()
    if lower_v in _PLACEHOLDER_NAMES:
        return 'there'
    if re.fullmatch(r'[A-Za-z]', v):
        return _name_from_email(email) or 'there'
    if '?' in v or _GARBLED_RE.search(v):
        return _name_from_email(email) or 'there'
    if re.search(r'\d', v):
        return 'there'
    if '/' in v:
        if _CONJUNCTIONS_RE.match(v):
            return 'there'
        candidates = [n.strip().capitalize() for n in v.split('/') if n.strip()]
        if not candidates:
            return 'there'
        if email:
            prefix = re.sub(r'[.\-_]', '', email.split('@')[0].lower())
            for candidate in candidates:
                if candidate.lower() in prefix or prefix.startswith(candidate.lower()):
                    return candidate
        if linkedin:
            ll = linkedin.lower()
            for candidate in candidates:
                if candidate.lower() in ll:
                    return candidate
        return candidates[0]
    return v

def fix_last_name(last):
    v = last.strip()
    if '/' in v:
        v = v.split('/')[0].strip()
    return v

_FL_SKIP_RE = re.compile(
    r'^(and/or|his/her|he/she|him/her|s/he|w/o|w/e|and/or|or/and)$',
    re.IGNORECASE,
)

def fix_first_line(text, canonical_company=''):
    if not text:
        return text
    if canonical_company and '/' not in canonical_company:
        for wrong, right in _COMPANY_EXACT.items():
            if right == canonical_company and wrong in text:
                text = text.replace(wrong, right)
                break
    def _fix_segment(m):
        segment = m.group(0)
        if _FL_SKIP_RE.match(segment.strip()):
            return segment
        return fix_company_slash(segment)
    text = re.sub(
        r'[A-Z][A-Za-z0-9&.,\' -]*/[A-Za-z0-9&.,\' -]+',
        _fix_segment,
        text,
    )
    if canonical_company and '/' not in canonical_company:
        idx = text.find(canonical_company)
        if idx != -1:
            after_idx = idx + len(canonical_company)
            after = text[after_idx:]
            after = re.sub(r'^\s*/[^.!?\n]*', '', after)
            text = text[:after_idx] + after
    return text.strip()


# ==============================================================================
# COLUMN DETECTION
# ==============================================================================

def _find_col(columns, *patterns):
    for pat in patterns:
        for col in columns:
            if re.search(pat, col, re.IGNORECASE):
                return col
    return None

def _detect_columns(df):
    cols = list(df.columns)
    return {
        'city':        _find_col(cols, r'subject.?line.?city', r'city.*subject'),
        'university':  _find_col(cols, r'local university', r'prominent university', r'\buniversity\b'),
        'school':      _find_col(cols, r'local school', r'\bschool\b'),
        'company':     _find_col(cols, r'^company name$', r'^company$'),
        'normalized':  _find_col(cols, r'normaliz', r'normalize.?company', r'normalized.?name'),
        'cleaned':     _find_col(cols, r'cleaned.?name', r'clean.?name'),
        'first_line':  _find_col(cols, r'^first.?line$'),
        'first_name':  _find_col(cols, r'^first.?name$'),
        'last_name':   _find_col(cols, r'^last.?name$'),
        'full_name':   _find_col(cols, r'^full.?name$'),
        'email':       _find_col(cols, r'^email$', r'^email.?address$'),
        'linkedin':    _find_col(cols, r'linkedin', r'profile.?url'),
    }


# ==============================================================================
# DATAFRAME CLEANER
# ==============================================================================

def clean_dataframe(df):
    df = df.copy()
    for col in df.columns:
        df[col] = df[col].fillna('').astype(str)
    for col in df.columns:
        df[col] = df[col].apply(clean_cell)
    cm = _detect_columns(df)
    if cm['city']:
        df[cm['city']] = df[cm['city']].apply(fix_subject_city)
    if cm['university']:
        if cm['school']:
            df[cm['university']] = df.apply(
                lambda r: fix_university(r[cm['university']], r[cm['school']]), axis=1)
        else:
            df[cm['university']] = df[cm['university']].apply(fix_university)
    for col in [cm['company'], cm['normalized'], cm['cleaned']]:
        if col:
            df[col] = df[col].apply(fix_company_slash)
    if cm['first_line']:
        canonical_col = cm['normalized'] or cm['company']
        if canonical_col:
            df[cm['first_line']] = df.apply(
                lambda r: fix_first_line(r[cm['first_line']], r[canonical_col]), axis=1)
        else:
            df[cm['first_line']] = df[cm['first_line']].apply(fix_first_line)
    if cm['first_name']:
        df[cm['first_name']] = df.apply(
            lambda r: fix_first_name(
                r[cm['first_name']],
                r[cm['email']] if cm['email'] else '',
                r[cm['linkedin']] if cm['linkedin'] else '',
            ), axis=1)
    if cm['last_name']:
        df[cm['last_name']] = df[cm['last_name']].apply(fix_last_name)
        if cm['full_name'] and cm['first_name']:
            df[cm['full_name']] = df.apply(
                lambda r: f"{r[cm['first_name']]} {r[cm['last_name']]}".strip(), axis=1)
    for col in df.columns:
        df[col] = df[col].apply(lambda x: re.sub(r' {2,}', ' ', x).strip())
    return df


# ==============================================================================
# DIFF / SUMMARY / HOTSPOTS
# ==============================================================================

def detect_change_type(old, new):
    if new == "there":                                              return "Name placeholder"
    if new == "Your city":                                         return "City fix"
    if "/" in old and "/" not in new:                              return "Slash fix"
    if "&" in old and "&" not in new:                             return "HTML entity"
    if any(ord(c) < 32 for c in old):                             return "Control characters"
    if any(ord(c) > 127 for c in old) and all(ord(c) <= 127 for c in new):
                                                                   return "Encoding / accent"
    return "Other encoding"

def compute_diff(df_orig, df_clean):
    changes = []
    for col in df_orig.columns:
        if col not in df_clean.columns:
            continue
        orig  = df_orig[col].fillna("").astype(str)
        clean = df_clean[col].fillna("").astype(str)
        mask  = orig != clean
        for idx in df_orig.index[mask]:
            o, n = orig[idx], clean[idx]
            changes.append((idx + 2, col, o, n, detect_change_type(o, n)))
    return changes

def build_summary(changes, total_rows):
    by_col  = defaultdict(int)
    by_type = defaultdict(int)
    for _, col, _, _, ctype in changes:
        by_col[col]    += 1
        by_type[ctype] += 1
    return dict(by_col), dict(by_type)

def build_hotspots(changes):
    row_data = defaultdict(lambda: {"count": 0, "cols": set(), "types": set()})
    for row_num, col, _, _, ctype in changes:
        row_data[row_num]["count"] += 1
        row_data[row_num]["cols"].add(col)
        row_data[row_num]["types"].add(ctype)
    return sorted(row_data.items(), key=lambda x: -x[1]["count"])
