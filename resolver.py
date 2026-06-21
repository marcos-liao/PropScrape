"""
Platform Resolver
─────────────────
Input  : nama platform dari user (bebas, bisa typo)
Output : dict {name, domain, base_url, search_url_pattern}

Strategi:
  1. Fuzzy match ke seed list platform properti Indonesia yang dikenal
  2. Kalau tidak ketemu → verifikasi via DDG JSON API
  3. Kalau DDG gagal → coba tebak domain langsung (.com / .co.id / .id)
"""

import logging
import re
import time
import random
from difflib import get_close_matches
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

# ─── SEED LIST ────────────────────────────────────────────────────────────────
# Platform properti Indonesia yang sudah diketahui
# format: alias/nama umum → {domain, search_pattern}
KNOWN_PLATFORMS: dict[str, dict] = {
    "rumah123": {
        "name":    "Rumah123",
        "domain":  "www.rumah123.com",
        "pattern": "/jual/rumah/?search%5Bq%5D={kw}&search%5Bpage%5D={page}",
    },
    "99co": {
        "name":    "99.co",
        "domain":  "www.99.co",
        "pattern": "/id/jual/properti?q={kw}&page_num={page}",
    },
    "99": {
        "name":    "99.co",
        "domain":  "www.99.co",
        "pattern": "/id/jual/properti?q={kw}&page_num={page}",
    },
    "lamudi": {
        "name":    "Lamudi",
        "domain":  "www.lamudi.co.id",
        "pattern": "/buy/?q={kw}&page={page}",
    },
    "rumah": {
        "name":    "Rumah.com",
        "domain":  "www.rumah.com",
        "pattern": "/properti-dijual?q={kw}&page_num={page}",
    },
    "rumahcom": {
        "name":    "Rumah.com",
        "domain":  "www.rumah.com",
        "pattern": "/properti-dijual?q={kw}&page_num={page}",
    },
    "olx": {
        "name":    "OLX Properti",
        "domain":  "www.olx.co.id",
        "pattern": "/properti/q-{kw}?page={page}",
    },
    "urbanindo": {
        "name":    "Urbanindo",
        "domain":  "www.urbanindo.com",
        "pattern": "/jual?q={kw}&page={page}",
    },
    "propertyguru": {
        "name":    "PropertyGuru",
        "domain":  "www.propertyguru.co.id",
        "pattern": "/property-for-sale?freetext={kw}&page={page}",
    },
    "dotproperty": {
        "name":    "Dot Property",
        "domain":  "www.dotproperty.id",
        "pattern": "/properties-for-sale?keyword={kw}&page={page}",
    },
    "iproperty": {
        "name":    "iProperty",
        "domain":  "www.iproperty.co.id",
        "pattern": "/buy/?q={kw}&page={page}",
    },
    "rumahku": {
        "name":    "Rumahku",
        "domain":  "www.rumahku.com",
        "pattern": "/properti/jual?q={kw}&page={page}",
    },
    "siapproperti": {
        "name":    "Siap Properti",
        "domain":  "www.siapproperti.com",
        "pattern": "/dijual?q={kw}&page={page}",
    },
    "belikpr": {
        "name":    "BeliKPR",
        "domain":  "www.belikpr.com",
        "pattern": "/properti?q={kw}&page={page}",
    },
    "raywhite": {
        "name":    "Ray White",
        "domain":  "www.raywhite.co.id",
        "pattern": "/jual?location={kw}&page={page}",
    },
    "era": {
        "name":    "ERA Indonesia",
        "domain":  "www.era.id",
        "pattern": "/listing?q={kw}&page={page}",
    },
    "century21": {
        "name":    "Century 21",
        "domain":  "www.century21.co.id",
        "pattern": "/property-listing?q={kw}&page={page}",
    },
    "properti": {
        "name":    "Properti.com",
        "domain":  "www.properti.com",
        "pattern": "/dijual?q={kw}&page={page}",
    },
    "btnproperti": {
        "name":    "BTN Properti",
        "domain":  "btnproperti.co.id",
        "pattern": "/property?tab=perumahan&lokasi={kw}&page={page}",
    },
    "baleproperti": {
        "name":    "BTN Properti",
        "domain":  "btnproperti.co.id",
        "pattern": "/property?tab=perumahan&lokasi={kw}&page={page}",
    },
}

# Alias tambahan untuk handle variasi penulisan user
ALIASES = {
    "rumah 123":    "rumah123",
    "rumah-123":    "rumah123",
    "r123":         "rumah123",
    "99 co":        "99co",
    "99.co":        "99co",
    "olx properti": "olx",
    "olx property": "olx",
    "property guru":"propertyguru",
    "pg":           "propertyguru",
    "dot property": "dotproperty",
    "dot prop":     "dotproperty",
    "ray white":    "raywhite",
    "rw":           "raywhite",
    "c21":          "century21",
    "abad21":       "century21",
    "urban indo":   "urbanindo",
    "siap prop":    "siapproperti",
}


# ─── FUZZY MATCH ──────────────────────────────────────────────────────────────
def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def fuzzy_match(user_input: str) -> dict | None:
    """Coba cocokkan input user ke seed list. Return platform dict atau None."""
    normalized = _normalize(user_input)

    # Exact match dulu
    if normalized in KNOWN_PLATFORMS:
        return KNOWN_PLATFORMS[normalized]

    # Cek alias
    lower = user_input.strip().lower()
    if lower in ALIASES:
        key = ALIASES[lower]
        return KNOWN_PLATFORMS.get(key)

    # Cek apakah input adalah domain yang sudah dikenal (rumah123.com → rumah123)
    domain_stripped = re.sub(r'\.(com|co\.id|id|net|org)$', '', normalized)
    if domain_stripped in KNOWN_PLATFORMS:
        return KNOWN_PLATFORMS[domain_stripped]

    # Cek domain match ke domain field di seed list
    clean_input = re.sub(r'^(www\.)', '', user_input.strip().lower())
    for key, platform in KNOWN_PLATFORMS.items():
        domain = platform["domain"].lower().replace("www.", "")
        if clean_input == domain or clean_input == domain.split(".")[0]:
            return platform

    # Fuzzy match ke semua key + alias
    all_keys = list(KNOWN_PLATFORMS.keys()) + list(ALIASES.keys())
    close = get_close_matches(normalized, [_normalize(k) for k in all_keys], n=1, cutoff=0.6)
    if close:
        match_str = close[0]
        for k in all_keys:
            if _normalize(k) == match_str:
                key = ALIASES.get(k, k)
                return KNOWN_PLATFORMS.get(key)

    return None


# ─── DDG JSON API VERIFY ──────────────────────────────────────────────────────
def verify_via_ddg(user_input: str, session) -> dict | None:
    """
    Gunakan DDG Instant Answer JSON API untuk cari domain platform.
    Endpoint: https://api.duckduckgo.com/?q=...&format=json&no_redirect=1
    Tidak butuh scrape HTML, lebih stabil.
    """
    query = f"{user_input} properti indonesia situs resmi"
    url   = f"https://api.duckduckgo.com/?q={query.replace(' ', '+')}&format=json&no_redirect=1&kl=id-id"

    log.info(f"DDG API verify: '{user_input}'")
    try:
        r = session.get(url, fast=True, retries=2)
        if not r:
            return None

        data = r.json()

        # Cek AbstractURL (biasanya hasil Wikipedia/official site)
        abstract_url = data.get("AbstractURL", "")
        if abstract_url:
            domain = _extract_clean_domain(abstract_url)
            if domain:
                log.info(f"  DDG AbstractURL → {domain}")
                return _build_from_domain(user_input, domain)

        # Cek Results (listing hasil pencarian)
        for result in data.get("Results", []):
            href = result.get("FirstURL", "")
            if href:
                domain = _extract_clean_domain(href)
                if domain and _looks_like_property_site(domain):
                    log.info(f"  DDG Result → {domain}")
                    return _build_from_domain(user_input, domain)

        # Cek RelatedTopics
        for topic in data.get("RelatedTopics", []):
            href = topic.get("FirstURL", "")
            if href:
                domain = _extract_clean_domain(href)
                if domain and _looks_like_property_site(domain):
                    log.info(f"  DDG RelatedTopic → {domain}")
                    return _build_from_domain(user_input, domain)

    except Exception as e:
        log.warning(f"DDG API error: {e}")

    return None


def _extract_clean_domain(url: str) -> str | None:
    try:
        parsed = urlparse(url if url.startswith("http") else "https://" + url)
        host   = parsed.netloc.lower()
        if host and "." in host:
            return host
    except Exception:
        pass
    return None


def _looks_like_property_site(domain: str) -> bool:
    bad = {"wikipedia", "facebook", "google", "youtube", "twitter", "instagram"}
    return not any(b in domain for b in bad)


def _build_from_domain(user_input: str, domain: str) -> dict:
    """Bangun platform dict dari domain yang ditemukan, pakai search pattern generic."""
    name = user_input.strip().title()
    return {
        "name":    name,
        "domain":  domain,
        "pattern": "/search?q={kw}&page={page}",  # generic fallback
        "_generic": True,  # tandai sebagai generic (bukan dari seed list)
    }


# ─── DOMAIN GUESS ─────────────────────────────────────────────────────────────
def guess_domain(user_input: str, session) -> dict | None:
    """
    Last resort: coba domain langsung (kalau user input domain), lalu tebak TLD.
    """
    # Kalau input sudah berbentuk domain (ada titik), coba langsung dulu
    clean = re.sub(r"^https?://", "", user_input.strip().lower()).strip("/")
    if "." in clean:
        # Coba as-is dan www prefix
        for candidate in [clean, "www." + clean] if not clean.startswith("www.") else [clean]:
            try:
                r = requests.get(f"https://{candidate}", timeout=8, allow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0"})
                if r.status_code < 400:
                    log.info(f"  Domain langsung valid: {candidate}")
                    return _build_from_domain(user_input, candidate)
            except Exception:
                continue

    # Tebak dari nama slug + berbagai TLD
    slug = re.sub(r"[^a-z0-9]", "", _normalize(user_input))
    candidates = [
        f"www.{slug}.com", f"www.{slug}.co.id", f"www.{slug}.id",
        f"{slug}.com",     f"{slug}.co.id",     f"{slug}.id",
    ]
    for domain in candidates:
        log.debug(f"  Coba domain: {domain}")
        try:
            r = requests.get(f"https://{domain}", timeout=8, allow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code < 400:
                log.info(f"  Domain ditemukan via guess: {domain}")
                return _build_from_domain(user_input, domain)
        except Exception:
            continue
        time.sleep(0.5)
    return None


# ─── MAIN RESOLVE ─────────────────────────────────────────────────────────────
def resolve_platform(user_input: str, session) -> dict | None:
    """
    Resolve nama platform dari user ke dict platform lengkap.
    Coba: fuzzy match → DDG API → domain guess
    """
    log.info(f"Resolving: '{user_input}'")

    # 1. Fuzzy match ke seed list
    result = fuzzy_match(user_input)
    if result:
        log.info(f"  → Fuzzy match: {result['name']} ({result['domain']})")
        return result

    # 2. DDG JSON API
    result = verify_via_ddg(user_input, session)
    if result:
        log.info(f"  → DDG verify: {result['name']} ({result['domain']})")
        return result

    # 3. Domain guess
    result = guess_domain(user_input, session)
    if result:
        log.info(f"  → Domain guess: {result['name']} ({result['domain']})")
        return result

    log.warning(f"  → Tidak dapat resolve: '{user_input}'")
    return None


def resolve_all(user_inputs: list[str], session) -> tuple[list[dict], list[str]]:
    """
    Resolve semua input platform dari user.
    Return (resolved_platforms, failed_inputs)
    """
    resolved = []
    failed   = []

    for inp in user_inputs:
        inp = inp.strip()
        if not inp:
            continue
        platform = resolve_platform(inp, session)
        if platform:
            resolved.append(platform)
        else:
            failed.append(inp)
        time.sleep(random.uniform(0.5, 1.5))

    return resolved, failed
