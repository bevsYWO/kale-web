"""
core/general_cleaner.py — Section I4 pure-Python logic from kale_data_hub.py.

Universal cleaner with per-column rules and natural-language instruction parsing.
"""

import re

import pandas as pd

from core.cleaner import clean_cell, fix_first_name, _find_col
from core.recruiting_cleaner import fix_recruiting_city_from_row

# ==============================================================================
# CONSTANTS
# ==============================================================================

_GENERAL_NA_RE = re.compile(r'^(n/?a\.?|none|unknown|--|-)$', re.IGNORECASE)

ACTIONS = [
    "Remove rows containing",
    "Keep only rows containing",
    "Keep only numeric range",
    "Replace value",
    "Replace containing",
    "Title Case",
    "UPPERCASE",
    "lowercase",
    "Apply city clean",
    "Apply name clean",
    "Remove row if blank",
    "N/A -> blank",
    "Deduplicate",
]

ACTIONS_NO_VALUE = {
    "Title Case", "UPPERCASE", "lowercase",
    "Apply city clean", "Apply name clean",
    "Remove row if blank", "N/A -> blank",
    "Deduplicate",
}

ACTION_DESCRIPTIONS = {
    "Remove rows containing":     "Removes any row where this column contains one of the keywords you enter (comma-separated). Example: entering 'spa, salon' removes every row that has either word.",
    "Keep only rows containing":  "Keeps only rows where this column contains at least one of the keywords — removes everything else. Example: entering 'HVAC, plumber' keeps only those business types.",
    "Replace value":              "Replaces an exact cell value with another. Format: old text -> new text. Example: 'N/A -> Unknown' replaces every cell that says exactly N/A.",
    "Replace containing":         "Replaces any cell that contains the keyword with a new value. Format: keyword -> new text. Example: 'LLC -> ' removes LLC from every cell that contains it.",
    "Title Case":                 "Converts every word in this column to Title Case. Example: 'john smith' becomes 'John Smith'.",
    "UPPERCASE":                  "Converts every value in this column to ALL CAPS. Example: 'Vancouver' becomes 'VANCOUVER'.",
    "lowercase":                  "Converts every value in this column to all lowercase. Example: 'VANCOUVER' becomes 'vancouver'.",
    "Apply city clean":           "Fixes invalid city values — strips out street addresses, postal codes, and placeholders.",
    "Apply name clean":           "Fixes first-name issues — converts placeholder names to 'there', resolves slash-merged names, removes single letters.",
    "Remove row if blank":        "Removes any row where this column is empty or contains only whitespace.",
    "N/A -> blank":               "Converts common placeholder values (N/A, n/a, none, unknown, --, -) to an empty string.",
    "Keep only numeric range":    "Keeps only rows where this column contains a number within the specified range.",
    "Deduplicate":                "Removes rows with duplicate values in this column — keeps the first occurrence, removes the rest. Most useful for deduplicating by email when that is the only cleaning needed.",
}


# ==============================================================================
# MAIN CLEANER
# ==============================================================================

def clean_general_dataframe(df, rules):
    """
    Universal clean on every cell + optional per-column rules.
    Returns (kept_df, removed_df).
    """
    df = df.copy()
    for col in df.columns:
        df[col] = df[col].fillna('').astype(str)

    # Step 1 — Universal cell clean on every column
    for col in df.columns:
        df[col] = df[col].apply(clean_cell)

    # Step 2 — Auto-detect city column and clean it
    cols     = list(df.columns)
    city_col = _find_col(cols, r'^city$')
    zip_col  = _find_col(cols, r'^zip[\s_]?code$', r'^zip$', r'^postal[\s_]?code$')
    addr_col = _find_col(cols, r'^(street[\s_]?)?address[\s_]?(1|line)?$',
                               r'^full[\s_]?address$', r'^location$')
    if city_col:
        df[city_col] = df.apply(
            lambda r: fix_recruiting_city_from_row(
                r[city_col],
                r[zip_col]  if zip_col  else '',
                r[addr_col] if addr_col else '',
            ), axis=1)

    # Step 3 — Per-column rules
    email_col    = _find_col(cols, r'^email$', r'^email[\s_]?address$')
    linkedin_col = _find_col(cols, r'linkedin', r'profile[\s_]?url')
    removed_mask    = pd.Series([False] * len(df), index=df.index)
    removal_reasons = pd.Series(['']   * len(df), index=df.index)

    for rule in rules:
        col    = rule['column']
        action = rule['action']
        value  = rule.get('value', '')
        if col not in df.columns:
            continue

        if action == "Remove rows containing":
            keywords = [k.strip().lower() for k in value.split(',') if k.strip()]
            if not keywords:
                continue
            mask = df[col].str.lower().apply(lambda v: any(k in v for k in keywords))
            new  = mask & ~removed_mask
            removal_reasons[new] = df.loc[new, col].apply(
                lambda v: f"{col}: contains '{v}'")
            removed_mask |= mask

        elif action == "Keep only rows containing":
            keywords = [k.strip().lower() for k in value.split(',') if k.strip()]
            if not keywords:
                continue
            mask = ~df[col].str.lower().apply(lambda v: any(k in v for k in keywords))
            new  = mask & ~removed_mask
            removal_reasons[new] = f"{col}: not in keep list"
            removed_mask |= mask

        elif action == "Replace value":
            sep = '\u2192' if '\u2192' in value else ('->' if '->' in value else None)
            if sep:
                old, new_val = value.split(sep, 1)
                old, new_val = old.strip(), new_val.strip()
                df[col] = df[col].apply(lambda v: new_val if v.strip() == old else v)

        elif action == "Replace containing":
            sep = '\u2192' if '\u2192' in value else ('->' if '->' in value else None)
            if sep:
                old, new_val = value.split(sep, 1)
                old, new_val = old.strip(), new_val.strip()
                df[col] = df[col].apply(lambda v: new_val if old.lower() in v.lower() else v)

        elif action == "Title Case":
            df[col] = df[col].apply(lambda v: v.title() if v.strip() else v)

        elif action == "UPPERCASE":
            df[col] = df[col].str.upper()

        elif action == "lowercase":
            df[col] = df[col].str.lower()

        elif action == "Apply city clean":
            df[col] = df.apply(
                lambda r: fix_recruiting_city_from_row(
                    r[col],
                    r[zip_col]  if zip_col  else '',
                    r[addr_col] if addr_col else '',
                ), axis=1)

        elif action == "Apply name clean":
            df[col] = df.apply(
                lambda r: fix_first_name(
                    r[col],
                    r[email_col]    if email_col    else '',
                    r[linkedin_col] if linkedin_col else '',
                ), axis=1)

        elif action == "Remove row if blank":
            mask = df[col].str.strip() == ''
            new  = mask & ~removed_mask
            removal_reasons[new] = f"{col}: blank"
            removed_mask |= mask

        elif action in ("N/A -> blank", "N/A \u2192 blank"):
            df[col] = df[col].apply(
                lambda v: '' if _GENERAL_NA_RE.match(v.strip()) else v)

        elif action == "Keep only numeric range":
            range_m = re.match(r'(\d+(?:\.\d+)?)\s*[-\u2013]\s*(\d+(?:\.\d+)?)', value.strip())
            if range_m:
                lo, hi = float(range_m.group(1)), float(range_m.group(2))
                def _out_of_range(v, lo=lo, hi=hi):
                    try:
                        return not (lo <= float(str(v).strip()) <= hi)
                    except (ValueError, TypeError):
                        return True
                mask = df[col].apply(_out_of_range)
                new  = mask & ~removed_mask
                removal_reasons[new] = df.loc[new, col].apply(
                    lambda v: f"{col}: '{v}' not in range {value}")
                removed_mask |= mask

        elif action == "Deduplicate":
            _col_lower = df[col].str.strip().str.lower()
            _dup_mask  = (_col_lower.duplicated(keep='first')
                          & (_col_lower != '')
                          & ~removed_mask)
            removal_reasons[_dup_mask] = f'Duplicate {col}'
            removed_mask |= _dup_mask

    # Tidy whitespace
    for col in df.columns:
        df[col] = df[col].apply(lambda x: re.sub(r' {2,}', ' ', str(x)).strip())

    # Deduplicate by email (within this file)
    if email_col:
        _email_lower = df[email_col].str.strip().str.lower()
        _dup_mask    = (_email_lower.duplicated(keep='first')
                        & (_email_lower != '')
                        & ~removed_mask)
        removal_reasons[_dup_mask] = 'Duplicate email'
        removed_mask |= _dup_mask

    kept_df    = df[~removed_mask].copy()
    removed_df = df[removed_mask].copy()
    removed_df['_removal_reason'] = removal_reasons[removed_mask]
    return kept_df, removed_df


# ==============================================================================
# NATURAL LANGUAGE INSTRUCTION PARSER
# ==============================================================================

def _parse_quick_instructions(text, headers):
    """
    Parse plain-English instruction text into rule dicts.

    Format — one line per column:
        column name - instructions

    Returns (rules, warnings).
    """
    rules    = []
    warnings = []

    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue

        col_raw     = None
        instruction = None
        for sep in [' - ', ' \u2014 ', ': ']:
            if sep in line:
                col_raw, instruction = line.split(sep, 1)
                break
        if col_raw is None:
            warnings.append(f"Skipped (no separator found): '{line}'")
            continue

        col_raw     = col_raw.strip()
        instruction = instruction.strip()

        # Match column name against loaded headers (exact then partial)
        col = _find_col(headers, r'(?i)^' + re.escape(col_raw) + r'$')
        if not col:
            col = _find_col(headers, re.escape(col_raw))
        if not col:
            col_lower = col_raw.lower()
            for h in headers:
                if h.lower().startswith(col_lower) or col_lower.startswith(h.lower()):
                    col = h
                    break
        if not col:
            warnings.append(f"Column not found: '{col_raw}'")
            continue

        line_rules = _parse_instruction_to_rules(col, instruction)
        if line_rules:
            rules.extend(line_rules)
        else:
            warnings.append(f"No rules parsed for '{col_raw}': '{instruction}'")

    return rules, warnings


def _parse_instruction_to_rules(col, instruction):
    """Convert a single instruction string for one column into rule dicts."""
    rules = []
    instr = instruction.lower().replace('/', ',')

    # City / address fix
    if re.search(r'street|actual\s+city|city\s+value|us\s+city|real\s+city|city\s+only', instr):
        rules.append({'column': col, 'action': 'Apply city clean', 'value': ''})
        instr = re.sub(
            r'(actual\s+city\s+values?\s+in\s+\w+|city\s+values?|streets?|us\s+cities?'
            r'|actual\s+city|city\s+only)',
            '', instr)

    # Name fix
    if re.search(r'name\s+clean|fix\s+name|placeholder\s+name', instr):
        rules.append({'column': col, 'action': 'Apply name clean', 'value': ''})

    # N/A -> blank
    if re.search(r'\bn\s*/?\s*a\b|\bna\s+values?\b', instr):
        rules.append({'column': col, 'action': 'N/A -> blank', 'value': ''})

    # Numeric range: "1-5 only", "1 to 5", "values between 1 and 5"
    range_m = re.search(
        r'(\d+(?:\.\d+)?)\s*(?:-|to|\u2013)\s*(\d+(?:\.\d+)?)', instr)
    if range_m:
        lo, hi = range_m.group(1), range_m.group(2)
        rules.append({'column': col, 'action': 'Keep only numeric range',
                      'value': f"{lo}-{hi}"})

    # Case transforms
    if re.search(r'\btitle\s*case\b', instr):
        rules.append({'column': col, 'action': 'Title Case', 'value': ''})
    if re.search(r'\buppercase\b|\ball\s+caps\b', instr):
        rules.append({'column': col, 'action': 'UPPERCASE', 'value': ''})
    if re.search(r'\blowercase\b', instr):
        rules.append({'column': col, 'action': 'lowercase', 'value': ''})

    # "no blanks" / "not blank" — extract before processing "no X" terms
    if re.search(r'\bno\s+blank|\bnot\s+blank|\bremove\s+blank', instr):
        rules.append({'column': col, 'action': 'Remove row if blank', 'value': ''})
        instr = re.sub(r'\b(no|not|remove)\s+blank\w*\b', '', instr)

    def _strip_quotes(s):
        return re.sub(r'''['""\u2018\u2019\u201c\u201d]''', '', s).strip()

    # Collect remove/exclude terms -> Remove rows containing
    remove_terms = []

    # Pattern 1: "remove X, Y" / "exclude X" / "filter out X" / "drop X"
    # Matches the whole instruction so "remove non profit, church" works in one shot
    _rm = re.match(
        r'^(?:remove|exclude|filter\s+out|drop|delete)\s+(.+)$',
        instr.strip(), re.IGNORECASE,
    )
    if _rm:
        for t in re.split(r'(?:\s+and\s+|,\s*)', _rm.group(1), flags=re.IGNORECASE):
            t = _strip_quotes(re.sub(r'\s+', ' ', t).strip().rstrip('.'))
            if t and len(t) > 1:
                remove_terms.append(t)

    # Pattern 2: comma-segment "no X" / "no X and Y" (existing behaviour)
    for seg in re.split(r',\s*', instr):
        seg = seg.strip()
        m = re.match(r'^(?:has\s+)?no\s+(.+)$', seg, re.IGNORECASE)
        if m:
            for t in re.split(r'\s+and\s+', m.group(1), flags=re.IGNORECASE):
                t = _strip_quotes(re.sub(r'\s+', ' ', t).strip().rstrip('.'))
                if t and len(t) > 1:
                    remove_terms.append(t)

    if remove_terms:
        rules.append({'column': col, 'action': 'Remove rows containing',
                      'value': ', '.join(remove_terms)})

    return rules
