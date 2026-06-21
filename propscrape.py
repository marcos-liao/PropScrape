#!/usr/bin/env python3
"""
PropScrape — Indonesia Property Scraper
────────────────────────────────────────────────
Flow:
  1. User input platform(s) — pisah koma, boleh typo
  2. Verifikasi & koreksi nama → temukan domain (fuzzy match / DDG API / guess)
  3. User konfirmasi
  4. User input keyword
  5. Playwright browser scrape tiap platform (bypass JS + Cloudflare)
  6. Output HTML + log per sesi

Usage: python propscrape.py
"""

import re
import sys
from datetime import datetime
from pathlib import Path

import socket
import requests

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from logger_setup    import setup_logger, log_platform_header, log_platform_summary
from session         import Session
from resolver        import resolve_all
from browser         import BrowserManager
from generic_scraper import scrape_platform, TYPE_LABELS
from html_gen        import generate_html

OUTPUT_DIR = BASE_DIR / "output"


def _try_hostname(hostname: str) -> tuple[bool, int | None]:
    """Cek satu hostname: DNS + HTTP. Return (ok, status_code)."""
    try:
        socket.getaddrinfo(hostname, 443)
    except socket.gaierror:
        return False, None
    for scheme in ("https", "http"):
        try:
            r = requests.get(
                f"{scheme}://{hostname}",
                timeout=8,
                allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            return True, r.status_code
        except requests.exceptions.SSLError:
            return True, None   # DNS OK, SSL issue tapi domain exist
        except Exception:
            continue
    return True, None           # DNS OK, HTTP diblock — browser akan handle


def _check_domain(domain: str) -> str | None:
    """
    Verifikasi domain dan normalisasi www prefix.
    Return: domain yang bekerja (bisa dengan/tanpa www), atau None kalau tidak bisa diakses.

    Flow:
    1. Coba domain apa adanya (misalnya pashouses.id)
    2. Kalau gagal HTTP dan tidak punya www → coba www.pashouses.id
    3. Pakai versi yang berhasil
    """
    hostname = re.sub(r"^https?://", "", domain.lower()).split("/")[0]

    print(f"     Mengecek {hostname}...", end=" ", flush=True)
    ok, status = _try_hostname(hostname)

    if not ok:
        # DNS gagal total — coba www kalau belum ada
        if not hostname.startswith("www."):
            www_host = "www." + hostname
            print(f"\n     DNS gagal, coba {www_host}...", end=" ", flush=True)
            ok_www, status_www = _try_hostname(www_host)
            if ok_www:
                label = f"({status_www})" if status_www else "(DNS OK)"
                print(f"✓ {label}")
                return www_host
        print("✗ domain tidak ditemukan")
        return None

    # DNS berhasil — cek apakah HTTP memberikan 4xx/5xx
    if status and status >= 400 and not hostname.startswith("www."):
        www_host = "www." + hostname
        print(f"\n     HTTP {status}, coba {www_host}...", end=" ", flush=True)
        ok_www, status_www = _try_hostname(www_host)
        if ok_www and (status_www is None or status_www < 400):
            label = f"({status_www})" if status_www else "(DNS OK)"
            print(f"✓ {label}")
            return www_host

    # Domain asli berhasil
    label = f"({status})" if status else "(DNS OK, HTTP diblock — browser akan handle)"
    print(f"✓ {label}")
    return hostname


def _ask_manual_domain(label: str) -> dict | None:
    """
    Minta user input domain manual, cek keberadaannya.
    Return platform dict kalau valid, None kalau user skip atau domain tidak exist.
    """
    while True:
        manual = input(f"     Masukkan domain yang benar (Enter = skip): ").strip()
        if not manual:
            return None

        manual = re.sub(r"^https?://", "", manual).strip("/").lower()

        verified = _check_domain(manual)
        if verified:
            name = input(f"     Nama platform (Enter = '{verified}'): ").strip() or verified
            return {
                "name":     name,
                "domain":   verified,   # pakai domain yang sudah diverifikasi (bisa +www)
                "pattern":  "/search?q={kw}&page={page}",
                "_generic": True,
                "_manual":  True,
            }
        else:
            print(f"     ⚠️  Domain '{manual}' tidak dapat diakses.")
            retry = input("     Coba domain lain? [Y/n]: ").strip().lower()
            if retry == "n":
                return None


def _session_name(platforms: list[dict]) -> str:
    names = [re.sub(r"[^\w]", "", p["name"].lower()) for p in platforms]
    return "_".join(names[:4])


_SUPPORTED = "Static HTML  |  Next.js Pages Router  |  Next.js App Router (RSC)  |  Client-Side API  |  GraphQL"

TESTED_PLATFORMS = [
    ("Rumah123",      "rumah123.com",      "Next.js App Router (RSC)"),
    ("99.co",         "99.co",             "Next.js App Router (RSC)"),
    ("Lamudi",        "lamudi.co.id",      "Next.js Pages Router"),
    ("BTN Properti",  "btnproperti.co.id", "Static HTML / SSR"),
    ("Ray White",     "raywhite.co.id",    "Static HTML / SSR"),
    ("Pashouses",     "pashouses.id",      "Next.js Pages Router"),
    ("Brighton",      "brighton.com",      "Static HTML / SSR"),
    ("Jendela360",    "jendela360.com",    "Next.js Pages Router"),
]

EXCLUDED_DOMAINS = {
    "olx.co.id":           "Anti-bot protection terlalu agresif (blank page)",
    "www.olx.co.id":       "Anti-bot protection terlalu agresif (blank page)",
    "rumah.com":           "Situs sudah ditutup sejak 1 Desember 2023",
    "www.rumah.com":       "Situs sudah ditutup sejak 1 Desember 2023",
    "propertyguru.co.id":  "Situs sudah tidak beroperasi di Indonesia (DNS mati)",
    "www.propertyguru.co.id": "Situs sudah tidak beroperasi di Indonesia (DNS mati)",
    "century21.co.id":     "Search hanya via location picker (tidak support free text)",
    "www.century21.co.id": "Search hanya via location picker (tidak support free text)",
    "era.id":              "URL search 404, homepage minim listing",
    "www.era.id":          "URL search 404, homepage minim listing",
    "trovit.co.id":        "HTTP 401 — situs memblokir akses non-browser",
    "www.trovit.co.id":    "HTTP 401 — situs memblokir akses non-browser",
    "rumah.trovit.co.id":  "HTTP 401 — situs memblokir akses non-browser",
    "trovit.com":          "Situs global, bukan Indonesia",
    "www.trovit.com":      "Situs global, bukan Indonesia",
    "travelio.com":        "Platform sewa/rental, bukan marketplace jual properti",
    "www.travelio.com":    "Platform sewa/rental, bukan marketplace jual properti",
    "sinarmasland.com":    "Situs corporate developer, bukan marketplace properti",
    "www.sinarmasland.com":"Situs corporate developer, bukan marketplace properti",
    "ciputra.com":         "Situs corporate developer, bukan marketplace properti",
    "www.ciputra.com":     "Situs corporate developer, bukan marketplace properti",
    "pakuwon.com":         "Situs corporate developer, bukan marketplace properti",
    "www.pakuwon.com":     "Situs corporate developer, bukan marketplace properti",
    "pinhome.id":          "URL search tidak standar (location picker, bukan free text)",
    "www.pinhome.id":      "URL search tidak standar (location picker, bukan free text)",
    "primaland.id":        "Situs corporate developer, bukan marketplace properti",
    "www.primaland.id":    "Situs corporate developer, bukan marketplace properti",
    "properti.com":        "Domain Swiss, bukan Indonesia",
    "www.properti.com":    "Domain Swiss, bukan Indonesia",
    "agungsedayu.com":     "Situs corporate developer (domain down)",
    "www.agungsedayu.com": "Situs corporate developer (domain down)",
    "bsdcity-residential.com":     "Situs corporate developer, bukan marketplace properti",
    "www.bsdcity-residential.com": "Situs corporate developer, bukan marketplace properti",
    "summareconserpong.com":       "Situs corporate developer, bukan marketplace properti",
    "www.summareconserpong.com":   "Situs corporate developer, bukan marketplace properti",
    "ocbd.co.id":          "Situs corporate developer, bukan marketplace properti",
    "www.ocbd.co.id":      "Situs corporate developer, bukan marketplace properti",
    "cimanggisgolfestate.com":     "Situs corporate developer (403 Forbidden)",
    "www.cimanggisgolfestate.com": "Situs corporate developer (403 Forbidden)",
}

def main():
    print("=" * 60)
    print("  PropScrape — Indonesia Property Scraper")
    print(f"  Supports : {_SUPPORTED}")
    print("─" * 60)
    print("  Tested & berhasil:")
    for name, domain, scraper in TESTED_PLATFORMS:
        print(f"    {name:<16} {domain:<22} {scraper}")
    print("─" * 60)
    excluded = ", ".join(d for d in EXCLUDED_DOMAINS if not d.startswith("www."))
    print(f"  Excluded : {excluded}")
    print("=" * 60)

    light_session = Session()

    # ── Loop input platform — ulangi dari awal kalau tidak ada platform valid ──
    platforms = []
    while not platforms:
        print("\nContoh  : rumah123")
        print("Multi   : rumah123, 99co, lamudi")
        raw_input = input("Scrape di platform apa? ").strip()
        if not raw_input:
            print("Input tidak boleh kosong.")
            continue

        user_inputs = [x.strip() for x in raw_input.split(",") if x.strip()]

        # ── Resolve ─────────────────────────────────────────────
        print(f"\n[Verifikasi] Mencari domain untuk: {', '.join(user_inputs)}...")
        resolved, failed = resolve_all(user_inputs, light_session)

        # ── Konfirmasi per platform yang ditemukan ───────────────
        final_platforms = []

        for p in resolved:
            # Cek excluded list
            domain_bare = re.sub(r"^www\.", "", p["domain"].lower())
            if domain_bare in EXCLUDED_DOMAINS or p["domain"].lower() in EXCLUDED_DOMAINS:
                reason = EXCLUDED_DOMAINS.get(domain_bare) or EXCLUDED_DOMAINS.get(p["domain"].lower(), "")
                print(f"\n  ✗ {p['name']} ({p['domain']}) — EXCLUDED")
                print(f"    Alasan: {reason}")
                continue

            tag = " [generic]" if p.get("_generic") else ""
            print(f"\n  Ditemukan: {p['name']} → {p['domain']}{tag}")
            ans = input("  Benar? [Y/n]: ").strip().lower()
            if ans != "n":
                # Verifikasi domain — otomatis coba www jika perlu
                verified = _check_domain(p["domain"])
                if verified and verified != p["domain"]:
                    print(f"  → Domain dikoreksi: {p['domain']} → {verified}")
                    p["domain"] = verified
                if verified:
                    final_platforms.append(p)
                    print(f"  ✓ {p['name']} ({p['domain']}) ditambahkan")
                else:
                    print(f"  ⚠️  {p['domain']} tidak bisa diakses, skip.")
            else:
                print(f"  Masukkan domain yang benar untuk '{p['name']}':")
                result = _ask_manual_domain(p["name"])
                if result:
                    final_platforms.append(result)
                    print(f"  ✓ {result['name']} ({result['domain']}) ditambahkan")
                else:
                    print(f"  — {p['name']} dilewati")

        # ── Platform yang gagal di-resolve ───────────────────────
        for inp in failed:
            print(f"\n  ⚠️  '{inp}' tidak ditemukan otomatis.")
            ans = input(f"  Input domain manual untuk '{inp}'? [y/N]: ").strip().lower()
            if ans == "y":
                result = _ask_manual_domain(inp)
                if result:
                    final_platforms.append(result)
                    print(f"  ✓ {result['name']} ({result['domain']}) ditambahkan")
                else:
                    print(f"  — '{inp}' dilewati")

        if not final_platforms:
            print("\n  Tidak ada platform valid. Silakan coba lagi.\n")
            # while loop akan ulangi dari awal
        else:
            platforms = final_platforms

    print(f"\n  Platform yang akan di-scrape ({len(platforms)}):")
    for p in platforms:
        print(f"  • {p['name']} ({p['domain']})")

    # ── Input keyword ───────────────────────────────────────────
    keyword = input("\nKeyword pencarian (contoh: BR 3+1, rumah tangerang): ").strip()
    if not keyword:
        print("Keyword tidak boleh kosong.")
        sys.exit(1)

    # ── Mode ────────────────────────────────────────────────────
    print("\nMode browser:")
    print("  [1] Headless — browser tidak terlihat (default, lebih cepat)")
    print("  [2] Visible  — browser terbuka, bisa dipantau")
    headless = (input("Pilih [1/2, Enter = 1]: ").strip() or "1") == "1"

    # ── Setup ───────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(exist_ok=True)
    session_name = _session_name(platforms)
    log = setup_logger(session_name)

    log.info("=" * 55)
    log.info("PropScrape — Indonesia Property Scraper")
    log.info(f"Supports : {_SUPPORTED}")
    log.info(f"Platform : {', '.join(p['name'] for p in platforms)}")
    log.info(f"Keyword  : '{keyword}'")
    log.info(f"Headless : {headless}")
    log.info("=" * 55)

    # ── Scraping dengan Playwright ──────────────────────────────
    all_listings: list[dict]   = []
    results_per_platform: dict = {}   # name → (count, site_type)

    print()
    with BrowserManager(headless=headless) as bm:
        for i, platform in enumerate(platforms, 1):
            print(f"[{i}/{len(platforms)}] {platform['name']} ({platform['domain']})")
            log_platform_header(log, platform["name"], platform["domain"])

            listings, site_type = scrape_platform(platform, keyword, bm, logger=log)
            all_listings.extend(listings)
            results_per_platform[platform["name"]] = (len(listings), site_type)

            log_platform_summary(log, platform["name"], len(listings))

            if not listings:
                type_label = TYPE_LABELS.get(site_type, site_type)
                print(f"  ! {platform['name']}: 0 listing")
                print(f"    Scraper '{type_label}' tidak dapat mengekstrak data dari site ini.")
                print(f"    Cek log untuk detail penyebabnya.")

    # ── Summary ─────────────────────────────────────────────────
    log.info("=" * 55)
    log.info("SUMMARY SESI")
    log.info("=" * 55)
    log.info(f"  {'Platform':<28} {'Scraper':<30} {'Listing':>7}")
    log.info(f"  {'─'*65}")
    for name, (count, stype) in results_per_platform.items():
        label = TYPE_LABELS.get(stype, stype)
        log.info(f"  {name:<28} {label:<30} {count:>7}")
    log.info(f"  {'─'*65}")
    log.info(f"  {'TOTAL':<58} {len(all_listings):>7}")

    # ── Generate HTML ───────────────────────────────────────────
    slug = re.sub(r"[^\w]", "_", keyword.lower())
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    out  = OUTPUT_DIR / f"properti_{slug}_{ts}.html"

    html = generate_html(keyword, all_listings, platforms)
    out.write_text(html, encoding="utf-8")

    log_path = BASE_DIR / "log" / f"{session_name}_scrape.log"
    log.info(f"Output HTML : {out.resolve()}")
    log.info("Sesi selesai.")

    print("\n" + "=" * 60)
    print(f"  ✅ Selesai!")
    print(f"  📊 Total  : {len(all_listings)} listing dari {len(platforms)} platform")
    print(f"  📄 Output : {out.resolve()}")
    print(f"  📋 Log    : {log_path.resolve()}")
    print("=" * 60)


if __name__ == "__main__":
    main()
