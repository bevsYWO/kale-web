"""
core/cleaner.py — Section A logic from kale_data_hub.py (pure Python, no Streamlit).

Includes all cleaning functions: clean_cell, clean_dataframe, fix_* helpers,
detect_change_type, compute_diff, build_summary, build_hotspots.
"""

import html
import re
import unicodedata
from collections import defaultdict

import pandas as pd


# ==============================================================================
# LOW-LEVEL TEXT FIXERS
# ==============================================================================

def _fix_ctrl_digit(text):
    return re.sub(r'[\x16\x17]\d', 'e', text)

def _remove_control_chars(text):
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

# When UTF-8 bytes are decoded as Latin-1, bytes 0x80-0x9F become C1 control chars
# (U+0080-U+009F) instead of the cp1252 printable chars they represent (€, ‰, etc.).
# Remapping them first lets the cp1252 encode step succeed.
_C1_TO_CP1252 = str.maketrans({
    '\x80': '€', '\x82': '‚', '\x83': 'ƒ', '\x84': '„',
    '\x85': '…', '\x86': '†', '\x87': '‡', '\x88': 'ˆ',
    '\x89': '‰', '\x8a': 'Š', '\x8b': '‹', '\x8c': 'Œ',
    '\x8e': 'Ž', '\x91': '‘', '\x92': '’', '\x93': '“',
    '\x94': '”', '\x95': '•', '\x96': '–', '\x97': '—',
    '\x98': '˜', '\x99': '™', '\x9a': 'š', '\x9b': '›',
    '\x9c': 'œ', '\x9e': 'ž', '\x9f': 'Ÿ',
})

def _fix_mojibake(text):
    text = text.translate(_C1_TO_CP1252)
    try:
        return text.encode('cp1252').decode('utf-8')
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

# Ste. / Ste must be checked before St. / St so "Ste" is not partly matched by the St pattern
_STE_RE = re.compile(r'\bSte\.?(?=[\s\-,]|$)', re.IGNORECASE)
_ST_RE  = re.compile(r'\bSt\.?(?=[\s\-,]|$)',  re.IGNORECASE)


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
    text = _STE_RE.sub('Sainte', text)
    text = _ST_RE.sub('Saint',  text)
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

_CITY_EXACT_FIXES = {
    'whitchurch stouffville': 'Whitchurch-Stouffville',
    'toranto':                'Toronto',
    'side studio entrance':   'Your city',
    'riverside estates':      'Your city',
}


def fix_subject_city(value):
    v = value.strip()
    lower = v.lower()
    if lower in _CITY_EXACT_FIXES:
        return _CITY_EXACT_FIXES[lower]
    if not v or lower in ('your city',):
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
    'Universite de Laval':                      'Universite Laval',
    'Université de Laval':                      'Universite Laval',
    'Universite du Quebec Montral':             'Universite du Quebec a Montreal',
    'Universite du Quebec a Montral':           'Universite du Quebec a Montreal',
}

def _fix_garbled_uni(text):
    text = re.sub(r'(?<=[A-Za-z])3', 'e', text)   # 3 → é  (Universit3 → Universite)
    text = re.sub(r'\b3(?=[A-Za-z])', 'E', text)   # 3col → Ecol
    text = re.sub(r'(?<=[A-Za-z])2', 'e', text)    # Qu2bec → Quebec
    text = re.sub(r'(?<=[A-Za-z])1', 'i', text)    # 1le → ile
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
    'n/a', 'na', 'n.a.', 'none', 'unknown', '-', '--', '.', 'test',
})


def _ascii_rescue(raw):
    """Last-resort: pull first ASCII word (≥2 letters) from raw value."""
    parts = re.findall(r'[A-Za-z][A-Za-z\-]*', str(raw))
    for p in parts:
        if len(p) >= 2:
            return p[0].upper() + p[1:]
    return ''
_CONJUNCTIONS_RE = re.compile(
    r'^(and/or|his/her|he/she|him/her|s/he|w/o|w/e)$', re.IGNORECASE
)

def fix_first_name(first, email='', linkedin=''):
    raw = str(first).strip()
    v = _fix_name_encoding(raw)   # Ã© → é → e (mojibake fix + strip accents to plain ASCII)
    v = re.sub(r"^['‘’\"`]+", '', v).strip()
    v = re.sub(r"^~+", '', v).strip()
    if v:
        v = v[0].upper() + v[1:]
    if not v:
        return _name_from_email(email) or _ascii_rescue(raw) or 'there'
    lower_v = v.lower()
    if lower_v == 'there':
        # Re-uploaded from a previously-processed file — try to recover from email
        return _name_from_email(email) or 'there'
    if lower_v in _PLACEHOLDER_NAMES:
        return _name_from_email(email) or _ascii_rescue(raw) or 'there'
    if re.fullmatch(r'[A-Za-z]', v):
        return _name_from_email(email) or _ascii_rescue(raw) or 'there'
    if '?' in v or _GARBLED_RE.search(v) or not v.isascii():
        ascii_v = re.sub(r'[^\x00-\x7f]', '', v).replace('?', '').strip()
        if ascii_v and len(ascii_v) >= 2 and re.search(r'[A-Za-z]', ascii_v):
            return ascii_v[0].upper() + ascii_v[1:]
        return _name_from_email(email) or _ascii_rescue(raw) or 'there'
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

def _fix_ai_ark_name(first, email='', linkedin=''):
    """Clean First Name AI Ark: strip quoted nicknames, then apply standard fix_first_name."""
    v = str(first).strip()
    v = re.sub(r'\s+["“”].+?["“”]', '', v).strip()
    v = re.sub(r"\s+['‘’].+?['‘’]", '', v).strip()
    return fix_first_name(v, email, linkedin)


def fix_last_name(last):
    v = last.strip()
    if '/' in v:
        v = v.split('/')[0].strip()
    return v

_FL_SKIP_RE = re.compile(
    r'^(and/or|his/her|he/she|him/her|s/he|w/o|w/e|and/or|or/and)$',
    re.IGNORECASE,
)

_FL_TEXT_FIXES = {
    'stemeducation':                                    'stem education',
    'came across Ld A.':                                'came across LD&A.',
    'Canadian Council of Independent Laboratorie':      'Canadian Council of Independent Laboratories.',
}

_WAS_LOOKING_RE = re.compile(r'was looking for .+', re.IGNORECASE)


def fix_first_line(text, canonical_company=''):
    if not text:
        return text
    # Known verbatim fixes
    for wrong, right in _FL_TEXT_FIXES.items():
        if wrong in text:
            text = text.replace(wrong, right)
    # Remove guillemets
    text = text.replace('«', '').replace('»', '').strip()
    # Double-slash → spaced dash
    text = re.sub(r'\s*//\s*', ' - ', text).strip()
    # Double (or more) periods → single
    text = re.sub(r'\.\.+', '.', text)
    # Number glued to capitalised word: 88Inc → 88 Inc
    text = re.sub(r'(\d)([A-Z][a-z])', r'\1 \2', text)
    # Strip stray special chars
    text = re.sub(r'[#@>_*\[\]|]', '', text)
    # Add missing trailing period to "was looking for ..." sentences
    if _WAS_LOOKING_RE.search(text) and not text.rstrip().endswith('.'):
        text = text.rstrip() + '.'
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
        'city':              _find_col(cols, r'subject.?line.?city', r'city.*subject'),
        'university':        _find_col(cols, r'local university', r'prominent university', r'\buniversity\b'),
        'school':            _find_col(cols, r'local school', r'\bschool\b'),
        'company':           _find_col(cols, r'^company name$', r'^company$'),
        'normalized':        _find_col(cols, r'normaliz', r'normalize.?company', r'normalized.?name'),
        'cleaned':           _find_col(cols, r'cleaned.?name', r'clean.?name'),
        'first_line':        _find_col(cols, r'^first.?line$'),
        'first_name':        _find_col(cols, r'^first.?name$'),
        'last_name':         _find_col(cols, r'^last.?name$'),
        'full_name':         _find_col(cols, r'^full.?name$', r'^name$'),
        'email':             _find_col(cols, r'^email$', r'^email.?address$'),
        'linkedin':          _find_col(cols, r'linkedin', r'profile.?url'),
        'mx_records':        _find_col(cols, r'^mx_records$'),
        'mx_records_1':      _find_col(cols, r'^mx_records\.1$'),
        'email_host':        _find_col(cols, r'^email_host$'),
        'domain':            _find_col(cols, r'^domain$'),
        'region':            _find_col(cols, r'^region$', r'^state$'),
        'first_name_ai_ark': _find_col(cols, r'first.?name.?ai.?ark'),
    }


# ==============================================================================
# DATAFRAME CLEANER
# ==============================================================================

def clean_dataframe(df, first_name_mode='clean'):
    """Clean a dataframe in-place.

    first_name_mode:
      'clean' — fix encoding/placeholders but keep real names
      'there' — replace every First Name value with 'there'
    First Name AI Ark is always cleaned (never bulk-replaced).
    """
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
            df[col] = df[col].apply(fix_company_name)
    if cm['first_line']:
        canonical_col = cm['normalized'] or cm['company']
        if canonical_col:
            df[cm['first_line']] = df.apply(
                lambda r: fix_first_line(r[cm['first_line']], r[canonical_col]), axis=1)
        else:
            df[cm['first_line']] = df[cm['first_line']].apply(fix_first_line)
    if cm['first_name']:
        if first_name_mode == 'there':
            df[cm['first_name']] = 'there'
        else:
            df[cm['first_name']] = df.apply(
                lambda r: fix_first_name(
                    r[cm['first_name']],
                    r[cm['email']] if cm['email'] else '',
                    r[cm['linkedin']] if cm['linkedin'] else '',
                ), axis=1)
            if cm['full_name']:
                def _rescue_from_full(row):
                    if row[cm['first_name']] != 'there':
                        return row[cm['first_name']]
                    words = [w for w in _fix_name_encoding(str(row[cm['full_name']])).split()
                             if len(w) >= 2 and re.search(r'[A-Za-z]', w)]
                    if words:
                        return words[0][0].upper() + words[0][1:]
                    return 'there'
                df[cm['first_name']] = df.apply(_rescue_from_full, axis=1)
    if cm['first_name_ai_ark']:
        df[cm['first_name_ai_ark']] = df.apply(
            lambda r: _fix_ai_ark_name(
                r[cm['first_name_ai_ark']],
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
# FILTERING — ROW REMOVAL (Steps 1–3, 7–9)
# ==============================================================================

_BLOCKED_MX_KEYWORDS = frozenset({
    'mimecast', 'barracuda', 'proofpoint', 'microsoft', 'outlook', 'yahoo', 'aol',
})

_NON_CANADIAN_SCHOOLS = frozenset({
    'anglia ruskin university', 'baldwin wallace university', 'beacon college',
    'canisius university', 'case western reserve university',
    'central michigan university', 'christ the king seminary',
    'clarkson university', 'cleveland state university', 'curry college',
    'davenport university', 'didsbury college of education',
    'east tennessee state university', 'eastern michigan university',
    'elmira college', 'florida a&m university', 'florida college',
    'florida gulf coast university', 'florida polytechnic university',
    'florida southwestern state college', 'florida southern college',
    'florida state university', 'gannon university', 'jackson college',
    'jacksonville university', 'keiser university', 'kent state university',
    'kodiak college', 'lake erie college', 'lake superior state university',
    'lawrence technological university', 'macomb community college',
    'madonna university', 'michigan state university', 'mid michigan college',
    'monroe county community college', 'niagara university',
    'northern kentucky university', 'oakland university', 'oberlin college',
    "paul smith's college", 'rockland community college', 'rollins college',
    'suny buffalo state university', 'suny fredonia', 'suny oswego',
    'suny plattsburgh', 'suny plattsburgh at queensbury', 'saint leo university',
    'santa clara university', 'sattler college',
    'seminole state college of florida', 'south florida state college',
    'southeastern university', 'st clair county community college',
    'st. clair county community college', 'st. cloud state university',
    'st. lawrence university', 'st. petersburg college', 'stanford university',
    'state college of florida', 'state college of florida manatee-sarasota',
    'trinity college of florida', 'university at buffalo',
    'university of central florida', 'university of denver',
    'university of detroit mercy', 'university of florida',
    'university of houston-clear lake', 'university of miami',
    'university of michigan-dearborn', 'university of minnesota twin cities',
    'university of north carolina at charlotte', 'university of north florida',
    'university of puget sound', 'university of rochester',
    'university of south florida', 'university of south florida sarasota-manatee',
    'university of south florida st. petersburg', 'university of tampa',
    'university of vermont', 'university of washington',
    'university of wisconsin-stevens point at marshfield', 'utica university',
    'villanova college', 'warner university', 'wayne state university',
    'wellesley college', 'western washington university', 'wilberforce university',
    'withlacoochee technical institute', 'yale university',
    'curtin university', 'free university of bozen-bolzano',
    'university of otago', 'university of clermont auvergne',
    'university of essex', 'university of lucknow', 'university of stirling',
    'diocesan theological institute',
})

_SCHOOL_GARBAGE_RE = re.compile(
    r'there are no prominent|no prominent universit|no well-known university'
    r'|is in the united states|not located in canada|does not have'
    r'|the search yielded|no universities located|in spruce grove',
    re.IGNORECASE,
)

_NON_CANADIAN_REGIONS = frozenset({
    'fl', 'mi', 'ny', 'wa', 'ga', 'oh', 'ca', 'california', 'ma', 'me', 'mn',
    'nh', 'nv', 'pa', 'ut', 'vt', 'al', 'ak', 'tn', 'ct', 'ia', 'nc', 'nj',
    'va', 'nd', 'england', 'western australia', 'bolzano', 'barcelona',
    'redruth', 'truro', 'suresnes', 'westminster', 'oakland county',
    'grenoble', 'ciudad',
})

_NON_CANADIAN_CITIES = frozenset({
    'algonac', 'armada', 'avoca', 'belle isle', 'belleair bluffs', 'berkley',
    'birmingham', 'canton', 'casco', 'clawson', 'clay twp', 'croswell',
    'crowes mills', 'davenport', 'dover', 'eastpointe', 'eureka',
    'fort gratiot', 'fraser', 'gotha', 'gratiot', 'greater northdale',
    'holiday', 'huntington woods', 'ira', 'killingworth', 'lake mary',
    'lakeland', 'land o lakes', 'largo', 'longboat key', 'madison heights',
    'madeira beach', 'metamora', 'mount dora', 'novi', 'oak park',
    'ontario center', 'oxford', 'pleasant ridge', 'point roberts', 'port huron',
    'romeo', 'roseville', 'royal oak', 'saint clair', 'st clair', 'seffner',
    'south pasadena', 'spring hill', 'st clair shores', 'tavares',
    'terrace park', 'troy', 'wimauma', 'zephyrhills', 'bellingham',
    'ferndale', 'lynden', 'gainesville', 'marietta',
    'el prat de llobregat', 'walled lake', 'clinton township',
    'sterling heights', 'chula vista', 'new york',
})

_VALIDATION_COLS = {
    'overall_score', 'is_safe_to_send', 'is_valid_syntax', 'is_disposable',
    'is_role_account', 'mx_accepts_mail', 'mx_records', 'can_connect_smtp',
    'has_inbox_full', 'is_catch_all', 'is_deliverable', 'is_disabled',
    'is_spamtrap', 'is_free_email', 'status', 'status.1', 'overall_score.1',
    'is_safe_to_send.1', 'mx_accepts_mail.1', 'mx_records.1',
}


def _has_blocked_keyword(value):
    v = str(value).lower()
    return any(kw in v for kw in _BLOCKED_MX_KEYWORDS)


def filter_dataframe(df):
    """Remove rows failing validation rules (Steps 1–3, 7–9).
    Returns (kept_df, removed_df) where removed_df has a '_removed_reason' column.
    """
    df = df.copy()
    removed_parts = []
    cm = _detect_columns(df)

    def _drop(mask, reason):
        nonlocal df
        if not mask.any():
            return
        bad = df[mask].copy()
        bad['_removed_reason'] = reason
        removed_parts.append(bad)
        df = df[~mask].reset_index(drop=True)

    # Steps 1–3: blocked keywords in mx_records, mx_records.1, email_host, domain
    for key in ('mx_records', 'mx_records_1', 'email_host', 'domain'):
        col = cm.get(key)
        if col and col in df.columns:
            _drop(df[col].fillna('').apply(_has_blocked_keyword),
                  f'Blocked keyword in {col}')

    # Step 7: non-Canadian or invalid/blank school
    school_col = cm.get('school')
    if school_col and school_col in df.columns:
        def _bad_school(v):
            s = str(v).strip()
            if not s or s.lower() in ('none', 'n/a', 'na'):
                return True
            if _SCHOOL_GARBAGE_RE.search(s):
                return True
            return s.lower() in _NON_CANADIAN_SCHOOLS
        _drop(df[school_col].fillna('').apply(_bad_school), 'Non-Canadian or invalid school')

    # Step 8: non-Canadian region
    region_col = cm.get('region')
    if region_col and region_col in df.columns:
        _drop(
            df[region_col].fillna('').apply(
                lambda v: v.strip().lower() in _NON_CANADIAN_REGIONS),
            'Non-Canadian region',
        )

    # Step 9: non-Canadian city — only when region also confirms non-Canadian
    city_col = cm.get('city')
    if city_col and region_col and city_col in df.columns and region_col in df.columns:
        def _bad_city(row):
            region = str(row[region_col]).strip().lower()
            if region not in _NON_CANADIAN_REGIONS:
                return False
            return str(row[city_col]).strip().lower() in _NON_CANADIAN_CITIES
        _drop(df.apply(_bad_city, axis=1), 'Non-Canadian city')

    if removed_parts:
        removed_df = pd.concat(removed_parts, ignore_index=True)
    else:
        removed_df = pd.DataFrame(columns=list(df.columns) + ['_removed_reason'])
    return df, removed_df


def drop_validation_columns(df):
    """Drop email-validation columns (Step 4)."""
    to_drop = [c for c in df.columns if c.lower() in _VALIDATION_COLS]
    return df.drop(columns=to_drop, errors='ignore')


# ==============================================================================
# EXTENDED COMPANY NAME FIXER (Step 11)
# ==============================================================================

_COMPANY_NAME_FIXES = {
    'equipements colpron , les.':                   'Colpron Equipment',
    'boisvert & chartrand s.e.n.c.r.l.':            'Boisvert & Chartrand SENCRL',
    'h ae lys.':                                    'Haelyss',
    'melancon marceau grenier cohen s.e.n.c.':      'Melancon Marceau Grenier Cohen',
    'industries p.f..':                             'PF Industries',
}

_SENCRL_RE        = re.compile(r'\bS\.E\.N\.C\.R\.L\.', re.IGNORECASE)
_SENC_RE          = re.compile(r'\bS\.E\.N\.C\.', re.IGNORECASE)
_STOCK_TICKER_RE  = re.compile(
    r'\s*\([^)]*(?:TSXV|OTCQB|FSE|TSX|NYSE|NASDAQ)\s*:[^)]*\)', re.IGNORECASE
)
_LEGAL_DOT_RE     = re.compile(r'\b(Inc|Ltd|Ltée|Lté|Corp|LLP|LLC|Co)\.\s*$')
_SPACE_COMMA_RE   = re.compile(r'\s+,')
_DOUBLE_DOT_RE    = re.compile(r'\.\.+')


def fix_company_name(name):
    """Extends fix_company_slash with Step 11 normalization (SENCRL, tickers, trailing dots, etc.)."""
    name = name.strip()
    if not name:
        return name
    lower = name.lower()
    if lower in _COMPANY_NAME_FIXES:
        return _COMPANY_NAME_FIXES[lower]
    name = fix_company_slash(name)
    name = _STOCK_TICKER_RE.sub('', name).strip()
    name = _SENCRL_RE.sub('SENCRL', name)
    name = _SENC_RE.sub('SENC', name)
    name = _LEGAL_DOT_RE.sub(lambda m: m.group(1), name)
    name = _SPACE_COMMA_RE.sub(',', name)
    name = _DOUBLE_DOT_RE.sub('.', name)
    return name.rstrip('.').strip()


# ==============================================================================
# SUSPICIOUS ROW FLAGGING (Step 14)
# ==============================================================================

_FRENCH_ARTICLE_TRAIL_RE = re.compile(r',\s*(Les|Le|La|L\')\s*$', re.IGNORECASE)
_TICKER_REMAIN_RE        = re.compile(r'\b(TSXV|OTCQB|FSE|TSX|NYSE|NASDAQ)\b')
_ALL_CAPS_COMPANY_RE     = re.compile(r'^[A-Z0-9&.,\'\- ]+$')
_VALID_FL_RE             = re.compile(
    r'came across you (on google maps|guys on google maps)'
    r'|was looking for .+ businesses'
    r"|I'm building a list of Canadian SMBs",
    re.IGNORECASE,
)


def _company_flag(name):
    if not name:
        return ''
    issues = []
    if _FRENCH_ARTICLE_TRAIL_RE.search(name):
        issues.append('French article at end')
    if _SPACE_COMMA_RE.search(name):
        issues.append('Space before comma')
    if _TICKER_REMAIN_RE.search(name):
        issues.append('Stock ticker remaining')
    if len(name.strip()) <= 3:
        issues.append('Very short name')
    if _ALL_CAPS_COMPANY_RE.match(name.strip()) and len(name.strip()) > 5:
        issues.append('All caps')
    words = re.split(r'[\s,]+', name)
    short_inner = [w for w in words[:-1] if 1 <= len(re.sub(r'[^A-Za-z]', '', w)) <= 2]
    if short_inner:
        issues.append('Isolated short word')
    return '; '.join(issues)


def flag_suspicious(df):
    """Add _review_flag column for suspicious companies / unrecognized first lines (Step 14)."""
    df = df.copy()
    cm = _detect_columns(df)

    company_col    = cm.get('company') or cm.get('normalized') or cm.get('cleaned')
    first_line_col = cm.get('first_line')

    flags = pd.Series([''] * len(df), index=df.index, dtype=str)

    if company_col and company_col in df.columns:
        flags = df[company_col].apply(_company_flag)

    if first_line_col and first_line_col in df.columns:
        def _line_flag(val):
            if not val:
                return ''
            if _VALID_FL_RE.search(val):
                return ''
            return 'First line format unrecognized'
        line_flags = df[first_line_col].apply(_line_flag)
        flags = flags.combine(line_flags,
                              lambda a, b: '; '.join(f for f in [a, b] if f))

    df['_review_flag'] = flags
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
