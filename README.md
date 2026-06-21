# PropScrape

Indonesia property listing scraper. Input platform name(s), enter a keyword, and get a consolidated HTML report with listing cards (photo, price, location, specs, link).

## Features

- **Multi-platform** — scrape multiple property sites in one session
- **Auto-detect website type** — automatically determines the right scraping strategy:
  - Static HTML / SSR (BeautifulSoup + price-pattern discovery)
  - Next.js Pages Router (`__NEXT_DATA__`)
  - Next.js App Router / RSC (React Flight payload)
  - Client-Side / API Driven (Playwright network intercept)
  - GraphQL (query intercept + replay)
- **Smart platform resolution** — fuzzy match, alias, DuckDuckGo API lookup, domain guessing
- **Anti-detection** — random UA/viewport, Indonesian locale, human-like delays
- **Playwright browser** — handles JS rendering and Cloudflare challenges
- **HTML output** — listing cards with photo, price, location, specs, and link
- **Per-session logging** — log files rotated each run

## Tested Platforms

| Platform | Domain | Scraper Type |
|---|---|---|
| Rumah123 | rumah123.com | Next.js App Router (RSC) |
| 99.co | 99.co | Next.js App Router (RSC) |
| Lamudi | lamudi.co.id | Next.js Pages Router |
| BTN Properti | btnproperti.co.id | Static HTML / SSR |
| Ray White | raywhite.co.id | Static HTML / SSR |
| Pashouses | pashouses.id | Next.js Pages Router |
| Brighton | brighton.com | Static HTML / SSR |
| Jendela360 | jendela360.com | Next.js Pages Router |

## Installation

```bash
git clone https://github.com/your-username/propscrape.git
cd propscrape
pip install -r requirements.txt
playwright install chromium
```

## Usage

```bash
python propscrape.py
```

The script will prompt you for:
1. **Platform name(s)** — comma-separated, typos OK (e.g. `rumah123, lamudi, raywhite`)
2. **Search keyword** — e.g. `rumah tangerang`, `bogor kota`, `BR 3+1`
3. **Browser mode** — headless (default) or visible

Output files are saved next to `propscrape.py`:
- `output/` — HTML reports
- `log/` — session logs
- `debug/` — debug HTML dumps (when 0 listings found)

Can be run from any directory:
```bash
# From anywhere
python /path/to/propscrape/propscrape.py
```

## Example

```
============================================================
  PropScrape — Indonesia Property Scraper
  Supports : Static HTML | Next.js Pages Router | Next.js App Router (RSC) | Client-Side API | GraphQL
------------------------------------------------------------
  Tested & berhasil:
    Rumah123         rumah123.com           Next.js App Router (RSC)
    99.co            99.co                  Next.js App Router (RSC)
    Lamudi           lamudi.co.id           Next.js Pages Router
    ...
============================================================

Scrape di platform apa? rumah123, raywhite
Keyword pencarian: tangerang

=======================================================
SUMMARY SESI
=======================================================
  Platform                     Scraper                        Listing
  -----------------------------------------------------------------
  Rumah123                     Next.js App Router (RSC)            46
  Ray White                    Static HTML / SSR                   30
  -----------------------------------------------------------------
  TOTAL                                                            76
```

## Requirements

- Python 3.11+
- Playwright (Chromium)
- See `requirements.txt` for full list

## License

MIT License. See [LICENSE](LICENSE) for details.
