"""Cheap keyword prefilter that runs BEFORE any LLM call.

Purpose: most postings on a big company's board (sales, HR, unrelated
engineering) are obviously irrelevant to a CTI/DE/TH search. Sending them
to the scoring model wastes quota and — on free tiers — trips rate limits.
This filter cuts that bulk with zero API cost; the LLM still makes the
nuanced relevance call for everything that passes.

Tiered rules, in order:
1. Title contains a SPECIFIC security keyword  -> relevant (always wins,
   so "Threat Intelligence Solutions Engineer" survives the exclusions).
2. Title contains an EXCLUDED role keyword     -> not relevant.
3. Title contains a GENERIC security keyword   -> relevant.
4. Description mentions >= DESC_MIN_HITS distinct core terms -> relevant
   (catches vague titles like "Member of Technical Staff, Investigations").
5. Otherwise                                   -> not relevant.

Filtered-out postings are still marked seen by the caller, so they are
never re-examined. Tune the lists below if real jobs get filtered; the
run log records every skip.
"""

from __future__ import annotations

import re

from .models import JobPosting

# Tier 1: strong CTI/DE/TH signals — a title hit here always passes.
SPECIFIC_TITLE_KEYWORDS = [
    r"\bthreat",            # threat intel / hunting / detection / researcher
    r"\bintel",             # intelligence, intel analyst
    r"\bdetect",            # detection engineer(ing)
    r"\bhunt",              # threat hunter / hunting
    r"\bsoc\b",             # SOC analyst
    r"\bincident response\b",
    r"\bmalware",
    r"\bforensic",
    r"\bdfir\b",
    r"\bcsirt\b",
    r"\bintrusion",
    r"\binvestigat",        # investigator / investigations
    r"\babuse\b",           # abuse detection / anti-abuse
    r"\btrust (?:&|and) safety\b",
]

# Tier 2: clearly-off roles. Only applied when no specific keyword hit.
EXCLUDED_TITLE_KEYWORDS = [
    r"\bsales\b",
    r"\baccount (?:executive|manager)\b",
    r"\bmarketing\b",
    r"\brecruit",
    r"\btalent\b",
    r"\bpeople operations\b",
    r"\bhuman resources\b",
    r"\battorney\b",
    r"\bcounsel\b",
    r"\bparalegal\b",
    r"\bdesigner\b",
    r"\bproduct manager\b",
    r"\bproduct marketing\b",
    r"\bcustomer success\b",
    r"\bsupport engineer\b",
    r"\bsolutions? (?:engineer|architect|consultant)\b",
    r"\baccountant\b",
    r"\bfinance\b",
    r"\bpayroll\b",
    r"\bexecutive assistant\b",
    r"\badministrative\b",
]

# Tier 3: generic security signals — pass, and let the model judge fit.
GENERIC_TITLE_KEYWORDS = [
    r"\bsecurity\b",
    r"\bcyber",
    r"\binfosec\b",
]

# Tier 4: description fallback — needs several DISTINCT core terms so a
# passing mention ("we take security seriously") doesn't qualify.
DESC_CORE_TERMS = [
    r"\bthreat intel",
    r"\bthreat hunt",
    r"\bdetection engineer",
    r"\bmitre att&ck\b",
    r"\bincident response\b",
    r"\bmalware\b",
    r"\bsiem\b",
    r"\bedr\b",
    r"\bsecurity operations\b",
    r"\bthreat actor",
    r"\bindicators? of compromise\b",
    r"\biocs?\b",
    r"\bosint\b",
    r"\bdfir\b",
    r"\byara\b",
    r"\bsigma\b",
    r"\bcyber threat",
]
DESC_MIN_HITS = 3

_SPECIFIC = [re.compile(p, re.I) for p in SPECIFIC_TITLE_KEYWORDS]
_EXCLUDED = [re.compile(p, re.I) for p in EXCLUDED_TITLE_KEYWORDS]
_GENERIC = [re.compile(p, re.I) for p in GENERIC_TITLE_KEYWORDS]
_DESC = [re.compile(p, re.I) for p in DESC_CORE_TERMS]


def is_relevant(posting: JobPosting) -> bool:
    """True if the posting is plausibly relevant and worth an LLM score."""
    title = posting.title or ""
    if any(p.search(title) for p in _SPECIFIC):
        return True
    if any(p.search(title) for p in _EXCLUDED):
        return False
    if any(p.search(title) for p in _GENERIC):
        return True
    desc = posting.description or ""
    hits = sum(1 for p in _DESC if p.search(desc))
    return hits >= DESC_MIN_HITS
