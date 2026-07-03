"""Location parsing tests covering the format zoo real ATSes produce."""

import pytest

from jobscout.locations import parse_location


@pytest.mark.parametrize("raw,city,state,metro,remote", [
    ("Austin, TX", "Austin", "TX", "Austin Metro", False),
    ("Remote - US", None, None, None, True),
    ("Remote", None, None, None, True),
    ("USA, VA, Herndon", "Herndon", "VA", "Washington DC Metro", False),
    ("New York, NY", "New York", "NY", "New York Metro", False),
    ("New York", "New York", "NY", "New York Metro", False),  # city beats state name
    ("San Francisco", "San Francisco", "CA", "SF Bay Area", False),
    ("Nashville, Tennessee", "Nashville", "TN", "Nashville Metro", False),
    ("Overland Park, KS", "Overland Park", "KS", "Kansas City Metro", False),
    ("Remote (US) or Denver, CO", "Denver", "CO", "Denver Metro", True),
    ("", None, None, None, False),
])
def test_parse_location(raw, city, state, metro, remote):
    loc = parse_location(raw)
    assert loc.city == city
    assert loc.state == state
    assert loc.metro == metro
    assert loc.is_remote == remote
    assert loc.raw == raw  # raw always preserved


def test_unknown_city_still_captured():
    loc = parse_location("Boise, ID")
    assert loc.city == "Boise"
    assert loc.state == "ID"
    assert loc.metro is None  # not in METRO_MAP, and that's fine


def test_display_formats():
    assert parse_location("Remote - US").display() == "Remote (US)"
    assert parse_location("Austin, TX").display() == "Austin, TX"
    assert "Remote-eligible" in parse_location("Remote or Austin, TX").display()
