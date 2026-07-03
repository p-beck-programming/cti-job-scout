"""Parse the free-text location strings ATSes return into structured Locations.

ATS location fields are wildly inconsistent:
  Greenhouse: "Austin, TX", "Remote - US", "New York City", "USA, VA, Herndon"
  Lever:      "San Francisco", "Remote", "United States", "SF Bay Area"

Design decision: parsing is deterministic (no LLM) so location filters on the
dashboard behave predictably, and the raw string is always kept so nothing
is lost when a string doesn't match any pattern.
"""

from __future__ import annotations

import re

from .models import Location

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}
_STATE_NAME_TO_CODE = {v.lower(): k for k, v in US_STATES.items()}

# City -> (metro label, state). Covers the metros that dominate US security
# hiring plus everything that appeared in the postings you shared. Extend
# freely — unknown cities still parse, they just get no metro label.
METRO_MAP: dict[str, tuple[str, str]] = {
    # DC / NoVA / MD — the CTI capital
    "washington": ("Washington DC Metro", "DC"),
    "arlington": ("Washington DC Metro", "VA"),
    "herndon": ("Washington DC Metro", "VA"),
    "reston": ("Washington DC Metro", "VA"),
    "mclean": ("Washington DC Metro", "VA"),
    "chantilly": ("Washington DC Metro", "VA"),
    "annapolis junction": ("Washington DC Metro", "MD"),
    "columbia": ("Washington DC Metro", "MD"),
    "fort meade": ("Washington DC Metro", "MD"),
    "bethesda": ("Washington DC Metro", "MD"),
    # SF Bay Area
    "san francisco": ("SF Bay Area", "CA"),
    "oakland": ("SF Bay Area", "CA"),
    "san jose": ("SF Bay Area", "CA"),
    "palo alto": ("SF Bay Area", "CA"),
    "mountain view": ("SF Bay Area", "CA"),
    "sunnyvale": ("SF Bay Area", "CA"),
    # NYC
    "new york": ("New York Metro", "NY"),
    "new york city": ("New York Metro", "NY"),
    "brooklyn": ("New York Metro", "NY"),
    "jersey city": ("New York Metro", "NJ"),
    # Others common in security hiring
    "seattle": ("Seattle Metro", "WA"),
    "bellevue": ("Seattle Metro", "WA"),
    "austin": ("Austin Metro", "TX"),
    "boston": ("Boston Metro", "MA"),
    "canton": ("Boston Metro", "MA"),
    "denver": ("Denver Metro", "CO"),
    "boulder": ("Denver Metro", "CO"),
    "chicago": ("Chicago Metro", "IL"),
    "atlanta": ("Atlanta Metro", "GA"),
    "dallas": ("Dallas-Fort Worth Metro", "TX"),
    "plano": ("Dallas-Fort Worth Metro", "TX"),
    "nashville": ("Nashville Metro", "TN"),
    "franklin": ("Nashville Metro", "TN"),
    "brentwood": ("Nashville Metro", "TN"),
    "huntsville": ("Huntsville Metro", "AL"),
    "san antonio": ("San Antonio Metro", "TX"),
    "tampa": ("Tampa Metro", "FL"),
    "sarasota": ("Tampa Metro", "FL"),
    "st. paul": ("Minneapolis-St. Paul Metro", "MN"),
    "saint paul": ("Minneapolis-St. Paul Metro", "MN"),
    "minneapolis": ("Minneapolis-St. Paul Metro", "MN"),
    "louisville": ("Louisville Metro", "KY"),
    "overland park": ("Kansas City Metro", "KS"),
    "salt lake city": ("Salt Lake City Metro", "UT"),
    "phoenix": ("Phoenix Metro", "AZ"),
    "raleigh": ("Raleigh-Durham Metro", "NC"),
    "durham": ("Raleigh-Durham Metro", "NC"),
    "los angeles": ("Los Angeles Metro", "CA"),
    "santa monica": ("Los Angeles Metro", "CA"),
    "san diego": ("San Diego Metro", "CA"),
    "portland": ("Portland Metro", "OR"),
    "north palm beach": ("Miami-Palm Beach Metro", "FL"),
    "miami": ("Miami-Palm Beach Metro", "FL"),
}

_REMOTE_RE = re.compile(r"\b(remote|distributed|work\s*from\s*home|anywhere)\b", re.I)
_US_RE = re.compile(r"\b(usa?|u\.s\.a?\.?|united states)\b", re.I)


def _lookup_city(city: str) -> tuple[str | None, str | None]:
    """Return (metro, state) for a known city, else (None, None)."""
    hit = METRO_MAP.get(city.strip().lower())
    return hit if hit else (None, None)


def parse_location(raw: str) -> Location:
    """Best-effort parse of one ATS location string into a Location."""
    raw = (raw or "").strip()
    loc = Location(raw=raw)
    if not raw:
        return loc

    if _REMOTE_RE.search(raw):
        loc.is_remote = True
    if _US_RE.search(raw):
        loc.country = "US"

    # Tokenize on commas, hyphens-as-separators, pipes, slashes, "or"/"and",
    # and parentheses ("Remote (US) or Denver, CO" -> Remote, US, Denver, CO).
    tokens = [
        t.strip()
        for t in re.split(r"[,|/()]| - |\bor\b|\band\b", raw)
        if t.strip()
    ]

    for token in tokens:
        upper = token.upper()
        lower = token.lower()
        if upper in US_STATES and len(upper) == 2:
            loc.state = loc.state or upper
            loc.country = "US"
        elif lower in _STATE_NAME_TO_CODE:
            # Ambiguity note: "New York" and "Washington" are both a state
            # name and a major city. Security hiring almost always means the
            # city, so METRO_MAP (checked next) wins over the state reading.
            metro, st = _lookup_city(lower)
            if metro:
                loc.city = loc.city or token.title()
                loc.metro = loc.metro or metro
                loc.state = loc.state or st
            else:
                loc.state = loc.state or _STATE_NAME_TO_CODE[lower]
            loc.country = "US"
        elif not _REMOTE_RE.search(token) and not _US_RE.fullmatch(token):
            metro, st = _lookup_city(lower)
            if metro:
                loc.city = loc.city or token.title()
                loc.metro = loc.metro or metro
                loc.state = loc.state or st
                loc.country = "US"
            elif loc.city is None and re.search(r"[a-zA-Z]", token):
                # Unknown token: assume it's a city we don't have a metro for.
                loc.city = token.title()

    return loc


def parse_locations(raws: list[str]) -> list[Location]:
    """Parse and de-duplicate a list of location strings."""
    seen: set[str] = set()
    out: list[Location] = []
    for raw in raws:
        loc = parse_location(raw)
        key = f"{loc.city}|{loc.state}|{loc.is_remote}|{loc.raw.lower()}"
        if key not in seen:
            seen.add(key)
            out.append(loc)
    return out
