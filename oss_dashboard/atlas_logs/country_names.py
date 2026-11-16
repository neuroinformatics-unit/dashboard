"""Map ISO 3166-1 alpha-2 country codes to their full English names.

This is a display-only concern, mirroring ``atlas_names.py``/``tool_names.py``:
the summary Parquet keeps the raw two-letter code produced by
``geoip.CountryLookup`` (see ``atlas_logs/geoip.py``), and this module maps
that code to a human-readable name for the dashboard page.
"""

from __future__ import annotations

from babel import Locale

from oss_dashboard.atlas_logs.constants import UNKNOWN_COUNTRY

_TERRITORIES = Locale("en").territories


def display_country(country_code: str) -> str:
    """Return the full country name for an ISO 3166-1 alpha-2 code.

    Falls back to the code itself for anything Babel doesn't recognise,
    including the ``"??"`` placeholder ``geoip`` uses for unresolved IPs.
    """
    if country_code == UNKNOWN_COUNTRY:
        return "Unknown"
    return _TERRITORIES.get(country_code, country_code)
