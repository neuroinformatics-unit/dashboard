"""Map IP addresses to ISO country codes using the free ip-location-db data.

The ``@ip-location-db/geo-whois-asn-country`` dataset is published on the
jsDelivr CDN as two headerless CSVs (IPv4 and IPv6) of
``range_start,range_end,country_code``. We cache them under
``~/.dashboard/geoip`` and refresh monthly. Lookups are a binary search
over the sorted range-end column, with a per-IP memo because client IPs
repeat heavily in access logs.
"""

from __future__ import annotations

import bisect
import ipaddress
import logging
import time
from pathlib import Path

import requests

from oss_dashboard.atlas_logs.constants import (
    GEOIP_CACHE_DIR,
    GEOIP_IPV4_URL,
    GEOIP_IPV6_URL,
    GEOIP_MAX_AGE_DAYS,
    UNKNOWN_COUNTRY,
)

logger = logging.getLogger(__name__)


class CountryLookup:
    """In-memory IPv4/IPv6 range table with a memoised ``lookup``."""

    def __init__(
        self,
        v4: tuple[list[int], list[int], list[str]],
        v6: tuple[list[int], list[int], list[str]],
    ) -> None:
        self._v4_starts, self._v4_ends, self._v4_cc = v4
        self._v6_starts, self._v6_ends, self._v6_cc = v6
        self._memo: dict[str, str] = {}

    def lookup(self, ip: str) -> str:
        """Return the ISO country code for ``ip`` or ``"??"`` if unknown."""
        cached = self._memo.get(ip)
        if cached is not None:
            return cached

        country = self._resolve(ip)
        self._memo[ip] = country
        return country

    def _resolve(self, ip: str) -> str:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return UNKNOWN_COUNTRY

        value = int(addr)
        if addr.version == 4:
            starts, ends, codes = (
                self._v4_starts,
                self._v4_ends,
                self._v4_cc,
            )
        else:
            starts, ends, codes = (
                self._v6_starts,
                self._v6_ends,
                self._v6_cc,
            )

        idx = bisect.bisect_left(ends, value)
        if idx < len(starts) and starts[idx] <= value <= ends[idx]:
            return codes[idx]
        return UNKNOWN_COUNTRY


def _cache_path(cache_dir: Path, name: str) -> Path:
    return cache_dir / name


def _is_fresh(path: Path) -> bool:
    if not path.exists():
        return False
    age_days = (time.time() - path.stat().st_mtime) / 86_400
    return age_days < GEOIP_MAX_AGE_DAYS


def _download(url: str, dest: Path) -> None:
    logger.info("Downloading GeoIP ranges from %s", url)
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(response.content)


def _load_csv(path: Path) -> tuple[list[int], list[int], list[str]]:
    starts: list[int] = []
    ends: list[int] = []
    codes: list[str] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            start_s, end_s, code = line.split(",")
            starts.append(int(ipaddress.ip_address(start_s)))
            ends.append(int(ipaddress.ip_address(end_s)))
            codes.append(code)

    # The published data is already sorted, but do not rely on it: the
    # binary search needs ``ends`` strictly ascending.
    order = sorted(range(len(ends)), key=ends.__getitem__)
    starts = [starts[i] for i in order]
    ends = [ends[i] for i in order]
    codes = [codes[i] for i in order]
    return starts, ends, codes


def load_country_lookup(
    cache_dir: Path = GEOIP_CACHE_DIR,
    *,
    offline_ok: bool = True,
) -> CountryLookup:
    """Build a :class:`CountryLookup`, downloading the data if stale.

    If a refresh fails but a cached copy exists, the cached copy is used.
    """
    specs = [
        ("geo-whois-asn-country-ipv4.csv", GEOIP_IPV4_URL),
        ("geo-whois-asn-country-ipv6.csv", GEOIP_IPV6_URL),
    ]
    tables = []
    for name, url in specs:
        path = _cache_path(cache_dir, name)
        if not _is_fresh(path):
            try:
                _download(url, path)
            except requests.RequestException as error:
                if path.exists() and offline_ok:
                    logger.warning(
                        "GeoIP refresh failed (%s); using cached %s",
                        error,
                        path,
                    )
                else:
                    raise
        tables.append(_load_csv(path))

    return CountryLookup(tables[0], tables[1])
