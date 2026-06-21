"""
Generic Property Scraper — Multi-Strategy dengan Auto-Detect
─────────────────────────────────────────────────────────────
Tipe website yang didukung:
  A  Static HTML / SSR        → BeautifulSoup langsung
  B  Next.js Pages Router     → window.__NEXT_DATA__
  C  Next.js App Router (RSC) → window.__next_f (React Flight)
  D  Client-Side / API Driven → intercept XHR/fetch response
  E  GraphQL                  → kirim ulang query ke endpoint

Flow:
  1. detect_type()  → tentukan tipe A-E
  2. Jalankan scraper yang sesuai
  3. Fallback ke tipe berikutnya kalau 0 result
"""

import json
import logging
import random
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import Page, Request, Response, TimeoutError as PlaywrightTimeout
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.console import Console

from browser import human_delay

MAX_PAGES = 3
console   = Console()
log       = logging.getLogger(__name__)

TYPE_LABELS = {
    "A": "Static HTML / SSR",
    "B": "Next.js Pages Router",
    "C": "Next.js App Router (RSC)",
    "D": "Client-Side / API Driven",
    "E": "GraphQL",
}

# ─── COMMON SELECTORS ─────────────────────────────────────────────────────────
CARD_SELECTORS = [
    # Rumah123 (Next.js App Router)
    "[class*='max-w-card']",
    # BTN Properti
    "[class*='card_unit_properti']",
    # Generic card patterns
    "[class*='listing-card']", "[class*='property-card']",
    "[class*='card-listing']", "[class*='card-property']",
    "[class*='card-featured']", "[class*='listing-item']",
    "[class*='property-item']", "[class*='product-card']",
    "[class*='card_unit']",
    "article[class*='listing']", "article[class*='property']",
    "li[class*='listing']",     "li[class*='property']",
    "[data-testid*='listing']", "[data-testid*='property']",
    "[itemtype*='RealEstateListing']",
]

TITLE_SEL    = ["h2","h3","[class*='title']","[class*='name']","[class*='heading']"]
PRICE_SEL    = ["[class*='price']","[class*='harga']","[data-testid*='price']"]
LOCATION_SEL = ["[class*='location']","[class*='address']","[class*='area']","[class*='lokasi']",
                 "[class*='card-text']","[class*='region']","[class*='city']","[class*='district']"]
AGENT_SEL    = ["[class*='agent']","[class*='seller']","[class*='advertiser']"]

JSON_TITLE    = ["title","name","listingName","propertyName","heading","project_name"]
JSON_PRICE    = ["price","asking_price","priceInRupiah","listingPrice","price_display","harga",
                  "selling_price","all_in_price","base_price","normal_price","harga_jual","priceValue",
                  "list_price","offer_price","sale_price","discount_price"]
JSON_LOCATION = ["address","location","area","city","district","lokasi","alamat","region"]
JSON_IMAGE    = ["image","photo","thumbnail","coverPhoto","mainPhoto","primaryPhoto","image_url","foto"]
JSON_URL      = ["url","link","href","listingUrl","detailUrl","slug","property_url"]
JSON_LT       = ["landSize","land_size","lotArea","lt","luasTanah","luas_tanah"]
JSON_LB       = ["buildingSize","floor_size","floorArea","lb","luasBangunan","luas_bangunan"]
JSON_KT       = ["bedroom","bedroomCount","bedroom_count","kamarTidur","kamar_tidur"]
JSON_KM       = ["bathroom","bathroomCount","bathroom_count","kamarMandi","kamar_mandi"]


# ─── NORMALIZER ───────────────────────────────────────────────────────────────
def _first(d: dict, keys: list) -> str:
    for k in keys:
        v = d.get(k)
        if not v:
            continue
        if isinstance(v, dict):
            v = (v.get("display") or v.get("value") or v.get("formatted")
                 or v.get("text") or v.get("name") or v.get("label") or "")
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _get_image(item: dict) -> str:
    for k in JSON_IMAGE:
        v = item.get(k)
        if not v:
            continue
        if isinstance(v, str) and v.startswith("http"):
            return v
        if isinstance(v, list) and v:
            f = v[0]
            return (f if isinstance(f, str) else f.get("url") or f.get("src") or "")
        if isinstance(v, dict):
            return v.get("url") or v.get("src") or ""
    return ""


def format_price(value) -> str:
    if not value:
        return ""
    try:
        cleaned = re.sub(r"[^\d]", "", str(value))
        if not cleaned:
            return str(value)
        v = int(cleaned)
        if v >= 1_000_000_000:
            return f"Rp {v/1_000_000_000:.2f} M".rstrip("0").rstrip(".")
        if v >= 1_000_000:
            return f"Rp {v/1_000_000:.0f} Jt"
        return f"Rp {v:,}".replace(",", ".")
    except Exception:
        return str(value)


def _normalize(item: dict, source: str, base_url: str) -> dict | None:
    title = _first(item, JSON_TITLE)
    if not title:
        return None

    price_raw = _first(item, JSON_PRICE)
    url = _first(item, JSON_URL)
    if url and not url.startswith("http"):
        url = base_url.rstrip("/") + ("" if url.startswith("/") else "/") + url

    loc = _first(item, JSON_LOCATION)
    if not loc:
        loc_obj = item.get("location") or item.get("area") or {}
        if isinstance(loc_obj, dict):
            loc = (loc_obj.get("formattedAddress") or loc_obj.get("full_address")
                   or loc_obj.get("name") or ", ".join(filter(None, [
                       loc_obj.get("district",""), loc_obj.get("city",""), loc_obj.get("province","")
                   ])))

    price_label = price_raw if (price_raw and not price_raw.isdigit()) else format_price(price_raw)

    return {
        "source":      source,
        "title":       title,
        "price_label": price_label,
        "location":    loc or "",
        "lt":          _first(item, JSON_LT),
        "lb":          _first(item, JSON_LB),
        "kt":          _first(item, JSON_KT),
        "km":          _first(item, JSON_KM),
        "desc":        (item.get("description") or item.get("summary") or "")[:500],
        "agent":       _first(item, ["agentName","agent_name","sellerName","advertiserName","developer"])
                       or (item.get("agent") or item.get("user") or {}).get("name",""),
        "image":       _get_image(item),
        "url":         url,
    }


def _score_as_listing(sample: dict) -> int:
    """
    Skor seberapa mungkin sebuah dict adalah listing properti.
    Harus ada harga untuk dianggap listing (bukan UI component).
    """
    has_price = any(k in sample for k in JSON_PRICE)
    has_title = any(k in sample for k in JSON_TITLE)
    has_url   = any(k in sample for k in JSON_URL)
    has_image = any(k in sample for k in JSON_IMAGE)
    has_loc   = any(k in sample for k in JSON_LOCATION)
    # Listing properti HARUS punya harga
    if not has_price:
        return 0
    score = sum([has_price, has_title, has_url, has_image, has_loc])
    return score


def _find_listings_in_json(obj, depth=0) -> list[dict]:
    """Rekursif cari array listing di nested JSON."""
    if depth > 10:
        return []
    if isinstance(obj, list):
        if len(obj) >= 2 and all(isinstance(x, dict) for x in obj[:3]):
            score = _score_as_listing(obj[0])
            if score >= 2:
                return obj
        # Rekursif ke setiap element list (untuk React component tree, dll)
        for item in obj:
            if isinstance(item, (dict, list)):
                found = _find_listings_in_json(item, depth+1)
                if found:
                    return found
    if isinstance(obj, dict):
        # Cek key yang umum untuk listings terlebih dahulu
        for key in ["listings","properties","items","results","data","hits",
                    "searchResult","searchListings","propertyList","listingList",
                    "listing","property","propertyResults","projects","units"]:
            val = obj.get(key)
            if val:
                found = _find_listings_in_json(val, depth+1)
                if found:
                    return found
        # Baru cek semua values lainnya
        for val in obj.values():
            if isinstance(val, (dict, list)):
                found = _find_listings_in_json(val, depth+1)
                if found:
                    return found
    return []


# ─── TYPE DETECTION ───────────────────────────────────────────────────────────
def detect_type(page: Page) -> str:
    """
    Detect tipe website:
    B = Next.js Pages Router (__NEXT_DATA__ dengan pageProps berisi data)
    C = Next.js App Router   (__next_f RSC payload)
    E = GraphQL              (ada script/meta yang menyebut graphql)
    D = Client-Side / API    (__NEXT_DATA__ ada tapi pageProps kosong)
    A = Static HTML / SSR    (fallback)
    """
    try:
        # Cek GraphQL via script content (tidak perlu hit network)
        has_graphql = page.evaluate("""() => {
            const scripts = Array.from(document.querySelectorAll('script'));
            return scripts.some(s => s.src && s.src.includes('graphql')) ||
                   document.body.innerHTML.includes('"__typename"');
        }""")
        if has_graphql:
            log.debug("  Detected: GraphQL")
            return "E"
    except Exception:
        pass

    try:
        nd = page.evaluate("() => window.__NEXT_DATA__ || null")
        if nd:
            is_error_page = nd.get("page") in ("/_error", "/404", "/_not-found")
            pp = nd.get("props", {}).get("pageProps", {})
            is_error_pp = bool(pp and set(pp.keys()) <= {"statusCode", "status", "message", "error"})

            if not is_error_page and pp and len(pp) > 0 and not is_error_pp:
                log.debug("  Detected: Next.js Pages Router")
                return "B"
            elif not is_error_page:
                # pageProps kosong — cek apakah HTML sudah render data (SSR hybrid)
                html_cards = page.evaluate("""() => {
                    const sel = [
                        '[class*="card_unit"]','[class*="listing-card"]',
                        '[class*="property-card"]','[class*="card-listing"]',
                        '[class*="max-w-card"]','[class*="listing-item"]',
                        '[class*="property-item"]'
                    ];
                    return sel.reduce((n, s) => n + document.querySelectorAll(s).length, 0);
                }""")
                if html_cards >= 2:
                    log.debug(f"  Detected: Static HTML / SSR (SSR hybrid, {html_cards} kartu)")
                    return "A"
                log.debug("  Detected: Client-Side / API Driven (pageProps kosong)")
                return "D"
    except Exception:
        pass

    try:
        has_rsc = page.evaluate("() => !!(window.__next_f && window.__next_f.length > 0)")
        if has_rsc:
            log.debug("  Detected: Next.js App Router (RSC)")
            return "C"
    except Exception:
        pass

    log.debug("  Detected: Static HTML / SSR")
    return "A"


PRICE_RE = re.compile(
    r'Rp\.?\s*[\d.,]+\s*(?:Miliar|Milyar|Juta|Jt|M|rb|K)?(?:\s*[Nn]ego)?',
    re.I
)


# ─── SCRAPER TIPE A: Static HTML ──────────────────────────────────────────────
def scrape_type_a(page: Page, source: str, base_url: str) -> list[dict]:
    html  = page.content()
    soup  = BeautifulSoup(html, "lxml")
    items = []
    seen  = set()

    def _add(item):
        if item:
            key = item.get("url") or item.get("title")
            if key and key not in seen:
                seen.add(key)
                items.append(item)

    # ── Strategi 1: CSS class selectors yang dikenal ─────────────────────────
    for sel in CARD_SELECTORS:
        cards = soup.select(sel)
        if len(cards) >= 2:
            log.debug(f"  [A] selector '{sel}' → {len(cards)} kartu")
            for card in cards:
                _add(_parse_card_html(card, source, base_url))
            break

    # ── Strategi 2: Price-pattern discovery (works di website mana pun) ──────
    # Cari elemen yang mengandung teks harga Rp, lalu naik ke container
    # yang punya img + link → itu adalah kartu properti
    if not items:
        price_containers = set()
        for text_node in soup.find_all(string=PRICE_RE):
            node = text_node.parent
            for _ in range(8):
                if node is None or node.name in ("body", "html", "[document]", "footer", "header", "nav"):
                    break
                has_img  = bool(node.find("img"))
                has_link = bool(node.find("a", href=True))
                text_len = len(node.get_text(strip=True))
                if has_img and has_link and text_len > 30:
                    if id(node) not in price_containers:
                        price_containers.add(id(node))
                        _add(_parse_card_html(node, source, base_url))
                    break
                node = node.parent
        if items:
            log.debug(f"  [A] price-pattern discovery → {len(items)} kartu")

    # ── Strategi 3: JSON-LD structured data ──────────────────────────────────
    jsonld_count = 0
    for script in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL
    ):
        try:
            data = json.loads(script.group(1))
            objs = data if isinstance(data, list) else [data]
            for obj in objs:
                if obj.get("@type") in ("RealEstateListing", "Product", "House", "Apartment",
                                        "Offer", "SingleFamilyResidence", "Apartment"):
                    n = _normalize(obj, source, base_url)
                    if n:
                        _add(n)
                        jsonld_count += 1
                # Cek juga ItemList
                if obj.get("@type") == "ItemList":
                    for el in obj.get("itemListElement", []):
                        item_data = el.get("item", el)
                        n = _normalize(item_data, source, base_url)
                        if n:
                            _add(n)
                            jsonld_count += 1
        except Exception:
            pass
    if jsonld_count:
        log.debug(f"  [A] JSON-LD → {jsonld_count} listing")

    log.debug(f"  [A] total {len(items)} listing")
    return items


def _parse_card_html(card, source: str, base_url: str) -> dict | None:
    try:
        title_el = next((card.select_one(s) for s in TITLE_SEL if card.select_one(s)), None)
        price_el = next((card.select_one(s) for s in PRICE_SEL if card.select_one(s)), None)
        loc_el   = next((card.select_one(s) for s in LOCATION_SEL if card.select_one(s)), None)
        img_el   = card.select_one("img[src],img[data-src],img[data-lazy-src]")
        link_el  = card.select_one("a[href]")

        # Title: coba dari selector, fallback ke h-tag, lalu p/span pertama yang bukan harga
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            for htag in ("h2","h3","h4","h5"):
                el = card.find(htag)
                if el:
                    title = el.get_text(strip=True)
                    break
        if not title:
            for el in card.find_all(["p", "span", "div"]):
                txt = el.get_text(strip=True)
                if 10 < len(txt) < 200 and not PRICE_RE.search(txt) and len(el.find_all()) < 4:
                    title = txt
                    break
        if not title or len(title) < 4:
            return None

        img = ""
        if img_el:
            img = (img_el.get("src") or img_el.get("data-src") or
                   img_el.get("data-lazy-src") or img_el.get("data-original") or "")
            if img and not img.startswith("http"):
                img = urljoin(base_url, img)

        # Skip placeholder / blank images
        if img and ("blank" in img or "placeholder" in img or img.endswith("1x1.gif")):
            img = ""

        url = ""
        if link_el:
            href = link_el.get("href","")
            if href and not href.startswith(("javascript:", "#", "mailto:")):
                url = href if href.startswith("http") else urljoin(base_url, href)

        txt = card.get_text(" ", strip=True)

        # Price: dari selector atau regex di teks
        price_label = price_el.get_text(strip=True) if price_el else ""
        if not price_label:
            m = PRICE_RE.search(txt)
            price_label = m.group(0).strip() if m else ""

        # Location: dari selector atau teks setelah nama kota/kab umum
        location = loc_el.get_text(strip=True) if loc_el else ""
        if not location:
            m = re.search(r'(?:Kab\.|Kota|Kec\.)\s+[\w\s]+', txt, re.I)
            location = m.group(0).strip() if m else ""

        lt  = re.search(r"LT[:\s]*(\d+)", txt, re.I)
        lb  = re.search(r"LB[:\s]*(\d+)", txt, re.I)
        kt  = re.search(r"(\d+)\s*(?:KT|kamar\s*tidur|bedroom)", txt, re.I)
        km  = re.search(r"(\d+)\s*(?:KM|kamar\s*mandi|bathroom)", txt, re.I)

        return {
            "source":      source,
            "title":       title,
            "price_label": price_label,
            "location":    location,
            "lt":          lt.group(1) if lt else "",
            "lb":          lb.group(1) if lb else "",
            "kt":          kt.group(1) if kt else "",
            "km":          km.group(1) if km else "",
            "desc":        "",
            "agent":       "",
            "image":       img,
            "url":         url,
        }
    except Exception:
        return None


# ─── SEARCH FORM FINDER (untuk generic / unknown sites) ───────────────────────
def _use_search_form(page: Page, keyword: str) -> bool:
    """
    Coba temukan search form di halaman dan gunakan.
    Return True kalau berhasil navigasi ke halaman hasil.
    """
    input_selectors = [
        'input[type="search"]',
        'input[name="q"]', 'input[name="query"]', 'input[name="search"]',
        'input[name="keyword"]', 'input[name="kw"]',
        'input[placeholder*="cari" i]', 'input[placeholder*="search" i]',
        'input[placeholder*="lokasi" i]', 'input[placeholder*="properti" i]',
        'input[placeholder*="rumah" i]', 'input[placeholder*="keyword" i]',
        'input[class*="search" i]', 'input[class*="cari" i]',
    ]
    for sel in input_selectors:
        try:
            inp = page.query_selector(sel)
            if not inp:
                continue
            inp.triple_click()
            inp.type(keyword, delay=80)
            inp.press("Enter")
            page.wait_for_load_state("domcontentloaded", timeout=20_000)
            log.debug(f"  [search-form] berhasil via '{sel}' → {page.url}")
            return True
        except Exception:
            continue
    return False


# ─── SCRAPER TIPE B: Next.js Pages Router ─────────────────────────────────────
def scrape_type_b(page: Page, source: str, base_url: str) -> list[dict]:
    try:
        nd  = page.evaluate("() => window.__NEXT_DATA__")
        raw = _find_listings_in_json(nd)
        if not raw:
            return []
        results = [_normalize(x, source, base_url) for x in raw if isinstance(x, dict)]
        results = [r for r in results if r]
        log.debug(f"  [B] __NEXT_DATA__ → {len(results)} listing")
        return results
    except Exception as e:
        log.debug(f"  [B] error: {e}")
        return []


# ─── SCRAPER TIPE C: Next.js App Router (RSC) ─────────────────────────────────
def scrape_type_c(page: Page, source: str, base_url: str) -> list[dict]:
    try:
        chunks = page.evaluate("""() => {
            if (!window.__next_f) return null;
            return window.__next_f
                .filter(c => c && c[1] && typeof c[1] === 'string')
                .map(c => c[1]).join('\\n');
        }""")
        if not chunks:
            return []

        results   = []
        seen_urls = set()

        for line in chunks.splitlines():
            line = line.strip()
            if not line:
                continue

            # RSC format: "<id>:<payload>" ATAU plain JSON (tanpa ID prefix)
            if line[0].isdigit():
                # Ada ID prefix: potong di titik dua pertama
                colon = line.find(":")
                if colon == -1:
                    continue
                payload = line[colon+1:].strip()
            elif line[0] in ('{', '['):
                # Plain JSON langsung (chunk tanpa ID RSC)
                payload = line
            else:
                continue

            if not (payload.startswith("{") or payload.startswith("[")):
                continue

            try:
                data  = json.loads(payload)
                found = _find_listings_in_json(data)
                if found:
                    for item in found:
                        n = _normalize(item, source, base_url)
                        if n:
                            key = n.get("url") or n.get("title")
                            if key and key not in seen_urls:
                                seen_urls.add(key)
                                results.append(n)
            except Exception:
                continue

        log.debug(f"  [C] RSC → {len(results)} listing")
        return results
    except Exception as e:
        log.debug(f"  [C] error: {e}")
        return []


# ─── SCRAPER TIPE D: Client-Side / API Driven ─────────────────────────────────
def scrape_type_d(page: Page, source: str, base_url: str, url: str) -> list[dict]:
    """
    Intercept API responses saat navigasi.
    Cari response JSON yang berisi array listing.
    """
    captured: list[dict] = []

    def handle_response(response: Response):
        try:
            ct = response.headers.get("content-type","")
            if "json" not in ct:
                return
            if response.status != 200:
                return
            # Skip tracking/analytics endpoints
            skip = ["analytics","segment","gtm","facebook","tiktok","ads","doubleclick"]
            if any(s in response.url for s in skip):
                return
            data  = response.json()
            found = _find_listings_in_json(data)
            if found:
                log.debug(f"  [D] API hit: {response.url[:80]} → {len(found)} item")
                for item in found:
                    n = _normalize(item, source, base_url)
                    if n:
                        captured.append(n)
        except Exception:
            pass

    page.on("response", handle_response)

    try:
        page.goto(url, wait_until="networkidle", timeout=45_000)
    except PlaywrightTimeout:
        log.debug("  [D] networkidle timeout, lanjut dengan yang sudah di-capture")
    except Exception as e:
        log.debug(f"  [D] goto error: {e}")
    finally:
        page.remove_listener("response", handle_response)

    log.debug(f"  [D] total captured: {len(captured)} listing")
    return captured


# ─── SCRAPER TIPE E: GraphQL ──────────────────────────────────────────────────
def scrape_type_e(page: Page, source: str, base_url: str, keyword: str) -> list[dict]:
    """
    Intercept GraphQL request pertama, simpan query + variables,
    lalu kirim ulang query dengan keyword dan page yang kita inginkan.
    """
    captured_query: dict = {}

    def handle_request(request: Request):
        if "graphql" in request.url.lower() and request.method == "POST":
            try:
                body = request.post_data_json
                if body and not captured_query:
                    captured_query.update(body)
                    log.debug(f"  [E] GraphQL query captured dari {request.url}")
            except Exception:
                pass

    page.on("request", handle_request)
    try:
        page.goto(base_url, wait_until="networkidle", timeout=30_000)
    except Exception:
        pass
    finally:
        page.remove_listener("request", handle_request)

    if not captured_query:
        log.debug("  [E] Tidak ada GraphQL query yang di-capture")
        return []

    # Kirim ulang query dengan keyword
    results = []
    gql_url = base_url.rstrip("/") + "/graphql"
    try:
        import requests as req_lib
        headers = {
            "Content-Type": "application/json",
            "User-Agent":   "Mozilla/5.0",
            "Referer":      base_url,
        }
        # Inject keyword ke variables kalau ada
        if "variables" in captured_query:
            for k in ["keyword","q","query","search","location","area"]:
                if k in captured_query["variables"]:
                    captured_query["variables"][k] = keyword

        r = req_lib.post(gql_url, json=captured_query, headers=headers, timeout=15)
        if r.status_code == 200:
            data  = r.json()
            found = _find_listings_in_json(data)
            for item in found:
                n = _normalize(item, source, base_url)
                if n:
                    results.append(n)
    except Exception as e:
        log.debug(f"  [E] GraphQL request error: {e}")

    log.debug(f"  [E] GraphQL → {len(results)} listing")
    return results


# ─── WAIT HELPER ──────────────────────────────────────────────────────────────
def _wait_for_content(page: Page, progress, task):
    progress.update(task, description="  Menunggu konten...")
    for sel in CARD_SELECTORS[:8]:
        try:
            page.wait_for_selector(sel, timeout=6_000)
            return
        except PlaywrightTimeout:
            continue
    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeout:
        pass


# ─── DEBUG DUMP ───────────────────────────────────────────────────────────────
def _debug_dump(page: Page, source: str, page_num: int):
    debug_dir = Path(__file__).resolve().parent / "debug"
    debug_dir.mkdir(exist_ok=True)
    slug     = re.sub(r"[^\w]", "_", source.lower())
    html     = page.content()
    out_file = debug_dir / f"{slug}_p{page_num}.html"
    out_file.write_text(html, encoding="utf-8")

    soup    = BeautifulSoup(html, "lxml")
    classes = set()
    for el in soup.find_all(class_=True):
        for c in el.get("class",[]):
            if any(kw in c.lower() for kw in ["card","listing","property","item","result","house","rumah"]):
                classes.add(c)

    log.warning(f"  [debug] 0 listing — HTML: {out_file}")
    log.warning(f"  [debug] class relevan: {sorted(classes)[:30]}")


# ─── MAIN SCRAPER ─────────────────────────────────────────────────────────────
def scrape_platform(platform: dict, keyword: str, bm, logger=None) -> tuple[list[dict], str]:
    global log
    if logger:
        log = logger

    source    = platform["name"]
    base_url  = f"https://{platform['domain']}"
    pattern   = platform["pattern"]
    kw_enc    = keyword.replace(" ", "+")
    listings:  list[dict] = []
    site_type: str = "A"  # default, di-update setelah detect_type()

    total_steps = MAX_PAGES * 3

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=30),
        TextColumn("[green]{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"  [bold]{source}[/bold]", total=total_steps)

        pw_page = bm.new_page()

        # ── Load halaman 1 dengan intercept sejak awal (untuk tipe D) ──────────
        first_url  = base_url + pattern.format(kw=kw_enc, page=1)
        captured_d: list[dict] = []

        def _d_handler(response: Response):
            try:
                ct = response.headers.get("content-type", "")
                if "json" not in ct or response.status != 200:
                    return
                skip = ["analytics","segment","gtm","facebook","tiktok","ads","doubleclick","clarity","hotjar"]
                if any(s in response.url for s in skip):
                    return
                data  = response.json()
                found = _find_listings_in_json(data)
                if found:
                    log.debug(f"  [intercept] {response.url[:80]} → {len(found)} item")
                    for item in found:
                        n = _normalize(item, source, base_url)
                        if n:
                            captured_d.append(n)
            except Exception:
                pass

        is_generic = platform.get("_generic") or platform.get("_manual")
        domain     = platform["domain"]

        progress.update(task, description=f"  [bold]{source}[/bold] — loading...")
        pw_page.on("response", _d_handler)
        try:
            pw_page.goto(first_url, wait_until="networkidle", timeout=50_000)
        except PlaywrightTimeout:
            log.debug("  networkidle timeout hal 1, lanjut")
        except Exception as e:
            log.error(f"  Gagal load halaman pertama: {e}")
            pw_page.remove_listener("response", _d_handler)
            pw_page.close()
            return [], site_type
        pw_page.remove_listener("response", _d_handler)

        # Cek apakah halaman ini 404/error
        def _is_error_page() -> bool:
            try:
                return pw_page.evaluate("""() => {
                    const nd = window.__NEXT_DATA__;
                    if (nd) {
                        if (nd.page === '/_error') return true;
                        const pp = nd.props && nd.props.pageProps;
                        if (pp && (pp.statusCode >= 400 || pp.status >= 400)) return true;
                    }
                    const t = document.title.toLowerCase();
                    return t.includes('404') || t.includes('not found') ||
                           t.includes('page not found') || t.includes('tidak ditemukan');
                }""")
            except Exception:
                return False

        # Kalau 404 dan domain tidak punya www → retry dengan www
        if _is_error_page() and not domain.startswith("www."):
            www_domain   = "www." + domain
            www_base     = f"https://{www_domain}"
            www_first    = www_base + pattern.format(kw=kw_enc, page=1)
            log.info(f"  404 tanpa www → coba {www_domain}")
            progress.update(task, description=f"  [bold]{source}[/bold] — retry www...")
            pw_page.on("response", _d_handler)
            try:
                pw_page.goto(www_first, wait_until="networkidle", timeout=50_000)
            except PlaywrightTimeout:
                log.debug("  networkidle timeout www, lanjut")
            except Exception:
                pass
            pw_page.remove_listener("response", _d_handler)
            if not _is_error_page():
                # www berhasil — update base_url dan domain untuk halaman berikutnya
                base_url = www_base
                domain   = www_domain
                first_url = www_first
                platform["domain"] = www_domain
                log.info(f"  www berhasil: {www_domain}")

        # Untuk generic site ATAU kalau masih 404 → coba search form dari homepage
        if (is_generic or _is_error_page()):
            if _is_error_page():
                log.info("  Masih 404, coba homepage")
                progress.update(task, description=f"  [bold]{source}[/bold] — homepage...")
                pw_page.on("response", _d_handler)
                try:
                    pw_page.goto(base_url, wait_until="domcontentloaded", timeout=30_000)
                except Exception:
                    pass
                pw_page.remove_listener("response", _d_handler)

            progress.update(task, description=f"  [bold]{source}[/bold] — cari search form...")
            used_form = _use_search_form(pw_page, keyword)
            if used_form:
                pw_page.on("response", _d_handler)
                try:
                    pw_page.wait_for_load_state("networkidle", timeout=20_000)
                except PlaywrightTimeout:
                    pass
                pw_page.remove_listener("response", _d_handler)
                log.info(f"  Search form → {pw_page.url}")
            else:
                log.info("  Search form tidak ditemukan, lanjut dengan halaman saat ini")

        # Detect tipe setelah halaman hasil load
        site_type = detect_type(pw_page)

        # Jika tipe D tapi belum ada yang di-capture, coba scroll
        if site_type == "D" and not captured_d:
            try:
                pw_page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
                pw_page.wait_for_timeout(2000)
                pw_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                pw_page.wait_for_timeout(2000)
            except Exception:
                pass

        type_label = TYPE_LABELS.get(site_type, f"Type {site_type}")
        log.info(f"  SCRAPER  : {type_label}")
        progress.update(task, description=f"  [bold]{source}[/bold] — {type_label}")
        progress.advance(task)

        # Gunakan hasil intercept halaman 1 sebagai bonus (semua tipe)
        intercept_bonus = list(captured_d) if captured_d else []
        if intercept_bonus:
            log.debug(f"  Intercept halaman 1: {len(intercept_bonus)} item (akan digabung)")

        try:
            for page_num in range(1, MAX_PAGES + 1):
                url = base_url + pattern.format(kw=kw_enc, page=page_num)
                log.info(f"  Halaman {page_num}/{MAX_PAGES}: {url}")
                progress.update(task, description=f"  [bold]{source}[/bold] — hal {page_num}/{MAX_PAGES} [{site_type}]...")

                if site_type == "D":
                    if page_num == 1:
                        found = list(captured_d)
                        log.debug(f"  [D] hal 1 pakai cache intercept: {len(found)} item")
                    else:
                        found = scrape_type_d(pw_page, source, base_url, url)
                    if not found:
                        log.debug("  [D] intercept 0, fallback ke HTML parsing")
                        found = scrape_type_a(pw_page, source, base_url)
                    progress.advance(task, 2)
                else:
                    # Halaman 2+ perlu navigasi baru
                    if page_num > 1:
                        try:
                            pw_page.goto(url, wait_until="domcontentloaded", timeout=40_000)
                            _wait_for_content(pw_page, progress, task)
                        except PlaywrightTimeout:
                            log.error(f"  Timeout hal {page_num}, berhenti.")
                            progress.advance(task, 2)
                            break
                        except Exception as e:
                            log.error(f"  Error hal {page_num}: {e}")
                            progress.advance(task, 2)
                            break

                    # Ekstrak dengan strategi sesuai tipe
                    if site_type == "B":
                        found = scrape_type_b(pw_page, source, base_url)
                    elif site_type == "C":
                        found = scrape_type_c(pw_page, source, base_url)
                    elif site_type == "E":
                        found = scrape_type_e(pw_page, source, base_url, keyword)
                    else:  # A
                        found = scrape_type_a(pw_page, source, base_url)

                    # Fallback: kalau strategi utama gagal, coba semua strategi lain
                    if not found and site_type != "A":
                        log.debug(f"  [Type {site_type}] 0 result, fallback ke HTML")
                        found = scrape_type_a(pw_page, source, base_url)
                    if not found and site_type not in ("B", "C"):
                        log.debug("  Fallback ke RSC parser")
                        found = scrape_type_c(pw_page, source, base_url)
                    if not found and site_type != "B":
                        log.debug("  Fallback ke __NEXT_DATA__")
                        found = scrape_type_b(pw_page, source, base_url)

                    # Gabungkan intercept bonus ke halaman 1
                    if page_num == 1 and intercept_bonus:
                        found = list(found or []) + intercept_bonus

                    progress.advance(task, 2)

                before = len(listings)
                listings.extend(found or [])
                added = len(listings) - before

                progress.update(task, description=f"  [bold]{source}[/bold] — hal {page_num} ✓ +{added}")
                log.info(f"  Halaman {page_num} selesai | +{added} listing (total {len(listings)})")

                if added == 0:
                    if page_num == 1:
                        _debug_dump(pw_page, source, page_num)
                        if site_type == "D":
                            log.warning(f"  [D] Tidak ada API response yang ter-capture. "
                                        f"Cek debug HTML untuk lihat request apa yang dikirim.")
                    log.info("  Tidak ada listing baru, berhenti.")
                    break

                if page_num < MAX_PAGES:
                    delay = round(random.uniform(8.0, 13.0), 1)
                    progress.update(task, description=f"  [bold]{source}[/bold] — jeda {delay}s...")
                    time.sleep(delay)

        finally:
            pw_page.close()
            progress.update(task, description=f"  [bold]{source}[/bold] — [green]selesai {len(listings)}[/green]")

    # Deduplication
    seen, unique = set(), []
    for l in listings:
        key = l.get("url") or l.get("title")
        if key and key not in seen:
            seen.add(key)
            unique.append(l)

    log.info(f"  {source} SELESAI | {len(unique)} listing unik")

    if not unique:
        type_label = TYPE_LABELS.get(site_type, site_type)
        log.warning("  ┌─ TIDAK ADA LISTING DITEMUKAN ─────────────────────────")
        log.warning(f"  │  Scraper   : {type_label}")
        log.warning(f"  │  Domain    : {platform['domain']}")
        log.warning("  │  Kemungkinan penyebab:")
        log.warning("  │    1. URL search pattern tidak sesuai dengan site ini")
        log.warning("  │    2. Struktur HTML/JSON site berubah atau tidak standar")
        log.warning("  │    3. Site memblokir scraping (perlu cookie / login)")
        log.warning(f"  │  Cek debug/{source.lower().replace(' ','_')}_p1.html untuk detail")
        log.warning("  └────────────────────────────────────────────────────────")

    return unique, site_type
