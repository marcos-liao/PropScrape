"""
Browser Manager — Playwright
─────────────────────────────
Satu browser instance dipakai untuk semua platform dalam satu sesi.
Anti-detection: disable webdriver flag, realistic UA, random viewport.
"""

import logging
import random
import time

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, Playwright

log = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
]


class BrowserManager:
    def __init__(self, headless: bool = True, proxy: dict | None = None):
        self._pw:      Playwright     = None
        self._browser: Browser        = None
        self._context: BrowserContext = None
        self.headless = headless
        self.proxy    = proxy
        self._ua      = random.choice(USER_AGENTS)
        self._vp      = random.choice(VIEWPORTS)

    def start(self):
        log.info("Memulai browser Playwright (Chromium)...")
        self._pw = sync_playwright().start()

        launch_args = {
            "headless": self.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--disable-gpu",
                "--disable-http2",
            ],
        }
        if self.proxy:
            launch_args["proxy"] = {
                "server": self.proxy.get("http") or self.proxy.get("https"),
            }

        self._browser = self._pw.chromium.launch(**launch_args)
        self._context = self._browser.new_context(
            user_agent=self._ua,
            viewport=self._vp,
            locale="id-ID",
            timezone_id="Asia/Jakarta",
            # Sembunyikan bahwa ini Playwright
            extra_http_headers={
                "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
            },
        )

        # Patch navigator.webdriver = false
        self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
            Object.defineProperty(navigator, 'languages', {get: () => ['id-ID', 'id', 'en-US', 'en']});
            window.chrome = { runtime: {} };
        """)

        log.info(f"Browser ready | UA: {self._ua[:60]}... | viewport: {self._vp}")

    def new_page(self) -> Page:
        if not self._context:
            self.start()
        return self._context.new_page()

    def stop(self):
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
            log.info("Browser ditutup.")
        except Exception as e:
            log.warning(f"Error saat tutup browser: {e}")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()


def human_delay(min_s: float = 8.0, max_s: float = 13.0):
    """Jeda seperti manusia membaca halaman."""
    delay = random.uniform(min_s, max_s)
    log.debug(f"Jeda {delay:.1f} detik...")
    time.sleep(delay)
