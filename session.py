import logging
import random
import re
import time

import requests

log = logging.getLogger("scraper")

DELAY_MIN_DIRECT = 8.0
DELAY_MAX_DIRECT = 13.0
DELAY_MIN_PROXY  = 2.0
DELAY_MAX_PROXY  = 5.0

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
]

PROXY_SOURCES = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=anonymous",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
]


class ProxyManager:
    def __init__(self):
        self.proxies: list[str] = []
        self.bad:     set[str]  = set()
        self._load()

    def _load(self):
        log.info("Mengambil daftar proxy...")
        for url in PROXY_SOURCES:
            try:
                r = requests.get(url, timeout=10)
                lines = [
                    l.strip() for l in r.text.splitlines()
                    if re.match(r"\d+\.\d+\.\d+\.\d+:\d+", l.strip())
                ]
                self.proxies.extend(lines)
                log.debug(f"Proxy source {url[:60]} → {len(lines)} proxy")
                if len(self.proxies) >= 100:
                    break
            except Exception as e:
                log.warning(f"Gagal ambil proxy dari {url[:60]}: {e}")
        self.proxies = list(set(self.proxies) - self.bad)
        random.shuffle(self.proxies)
        log.info(f"Total proxy tersedia: {len(self.proxies)}")

    def get(self) -> dict | None:
        available = [p for p in self.proxies if p not in self.bad]
        if not available:
            log.warning("Semua proxy habis, refresh...")
            self.bad.clear()
            self._load()
            available = self.proxies
        if not available:
            return None
        proxy = random.choice(available)
        return {"http": f"http://{proxy}", "https": f"http://{proxy}"}

    def mark_bad(self, proxy_dict: dict):
        if proxy_dict:
            addr = proxy_dict.get("http", "").replace("http://", "")
            self.bad.add(addr)
            log.debug(f"Proxy di-blacklist: {addr}")


class Session:
    def __init__(self, proxy_mgr: ProxyManager | None = None):
        self.pm = proxy_mgr
        self._delay_min = DELAY_MIN_PROXY if proxy_mgr else DELAY_MIN_DIRECT
        self._delay_max = DELAY_MAX_PROXY if proxy_mgr else DELAY_MAX_DIRECT

    def _headers(self, referer: str = "https://www.google.com/") -> dict:
        return {
            "User-Agent":      random.choice(USER_AGENTS),
            "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer":         referer,
            "DNT":             "1",
        }

    def get(self, url: str, retries: int = 4, fast: bool = False, **kwargs) -> requests.Response | None:
        """
        fast=True → skip delay (untuk discovery/validation cepat)
        """
        proxy = self.pm.get() if self.pm else None
        proxy_addr = (proxy or {}).get("http", "direct").replace("http://", "")

        for attempt in range(retries):
            log.debug(f"GET attempt {attempt+1}/{retries} | proxy={proxy_addr} | {url}")
            try:
                r = requests.get(
                    url,
                    headers=self._headers(),
                    proxies=proxy,
                    timeout=15,
                    **kwargs,
                )
                if r.status_code == 200:
                    log.info(f"OK  {r.status_code} | {url[:90]}")
                    return r
                if r.status_code in (403, 429, 503):
                    log.warning(f"FAIL {r.status_code} | proxy={proxy_addr} | {url[:90]}")
                    if self.pm and proxy:
                        self.pm.mark_bad(proxy)
                        proxy = self.pm.get()
                        proxy_addr = (proxy or {}).get("http", "direct").replace("http://", "")
                else:
                    log.warning(f"FAIL {r.status_code} | {url[:90]}")
            except Exception as e:
                log.warning(f"ERROR attempt {attempt+1} | {e} | {url[:90]}")
                if self.pm and proxy:
                    self.pm.mark_bad(proxy)
                    proxy = self.pm.get()
                    proxy_addr = (proxy or {}).get("http", "direct").replace("http://", "")

            if not fast:
                delay = random.uniform(self._delay_min, self._delay_max)
                log.debug(f"Jeda {delay:.1f}s...")
                print(f"    [~] Jeda {delay:.1f} detik...")
                time.sleep(delay)
            else:
                time.sleep(random.uniform(1.0, 2.5))

        log.error(f"GAGAL setelah {retries} percobaan | {url[:90]}")
        return None
