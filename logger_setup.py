import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "log"


def setup_logger(session_name: str) -> logging.Logger:
    """
    session_name: misal 'rumah123_99co_lamudi'
    Log file    : log/rumah123_99co_lamudi_scrape.log
    Kalau file sudah ada, rename dulu dengan timestamp (rotate).
    """
    LOG_DIR.mkdir(exist_ok=True)

    log_file = LOG_DIR / f"{session_name}_scrape.log"

    if log_file.exists():
        ts  = datetime.fromtimestamp(log_file.stat().st_mtime).strftime("%Y%m%d_%H%M%S")
        dst = LOG_DIR / f"{session_name}_scrape_{ts}.log"
        shutil.move(str(log_file), str(dst))

    logger = logging.getLogger(session_name)
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


SITE_TYPE_LABEL = {
    "A": "Static HTML / SSR",
    "B": "Next.js Pages Router",
    "C": "Next.js App Router (RSC)",
    "D": "Client-Side / API Driven",
    "E": "GraphQL",
}


def log_platform_header(logger: logging.Logger, platform_name: str, domain: str,
                        site_type: str | None = None):
    """Tulis section break per platform di dalam log."""
    sep = "─" * 55
    logger.info(sep)
    logger.info(f"  PLATFORM : {platform_name}")
    logger.info(f"  DOMAIN   : {domain}")
    if site_type:
        label = SITE_TYPE_LABEL.get(site_type, f"Type {site_type}")
        logger.info(f"  SCRAPER  : {label}")
    logger.info(sep)


def log_platform_summary(logger: logging.Logger, platform_name: str, count: int):
    logger.info(f"  SELESAI  : {platform_name} → {count} listing")
    logger.info("─" * 55)
