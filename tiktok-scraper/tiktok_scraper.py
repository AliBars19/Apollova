"""TikTok Analytics Scraper — Aurora Account

Attaches to an existing Chrome session via CDP, crawls TikTok Studio's
content table, and stores all metrics in a local SQLite database.

Usage:
  1. Launch Chrome:  chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\\chrome-debug-profile"
  2. Log into TikTok in that Chrome window (first time only)
  3. Run:  python tiktok_scraper.py
"""

import asyncio
import csv
import json
import random
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

# ── Configuration ────────────────────────────────────────────────────────────

CDP_URL = "http://localhost:9222"
DB_PATH = Path(__file__).parent / "tiktok_analytics.db"
CSV_PATH = Path(__file__).parent / "tiktok_analytics.csv"
PAGE_TIMEOUT = 30_000
STUDIO_CONTENT_URL = "https://www.tiktok.com/creator-center/content"

# JS that runs inside the browser to extract video data from the content table.
# Each video row has an <a> with href containing /video/{id}.
# The row's text content has: duration, caption, [Pinned], date, privacy, views, likes, comments.
EXTRACT_VIDEOS_JS = r"""
() => {
    const results = [];
    const links = document.querySelectorAll('a[href*="/video/"]');
    for (const link of links) {
        const href = link.href;
        const match = href.match(/\/video\/(\d+)/);
        if (!match) continue;

        const videoId = match[1];

        // Each video row is wrapped in [data-tt="components_PostTable_Absolute"]
        const row = link.closest('[data-tt="components_PostTable_Absolute"]');
        if (!row) continue;

        const text = row.innerText || '';
        const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);

        const img = row.querySelector('img');
        const thumbUrl = img ? (img.src || '') : '';
        const caption = link.innerText.trim();

        results.push({
            video_id: videoId,
            caption: caption,
            thumbnail_url: thumbUrl,
            video_url: href,
            lines: lines
        });
    }
    return results;
}
"""


# ── Database ─────────────────────────────────────────────────────────────────

def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS videos (
            video_id        TEXT PRIMARY KEY,
            scraped_at      TIMESTAMP,
            status          TEXT DEFAULT 'pending',

            post_date       TEXT,
            caption         TEXT,
            hashtags        TEXT,
            thumbnail_url   TEXT,
            video_url       TEXT,

            views_raw       TEXT,
            likes_raw       TEXT,
            comments_raw    TEXT,

            views           INTEGER,
            likes           INTEGER,
            comments        INTEGER,

            error_message   TEXT
        );

        CREATE TABLE IF NOT EXISTS scrape_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at      TIMESTAMP,
            finished_at     TIMESTAMP,
            total_videos    INTEGER,
            scraped_count   INTEGER,
            failed_count    INTEGER,
            skipped_count   INTEGER
        );
    """)
    conn.commit()


# ── Parsing ──────────────────────────────────────────────────────────────────

def parse_number(raw: str | None) -> int | None:
    if not raw:
        return None
    raw = raw.strip().replace(",", "")
    try:
        if raw[-1] in ("M", "m"):
            return int(float(raw[:-1]) * 1_000_000)
        if raw[-1] in ("K", "k"):
            return int(float(raw[:-1]) * 1_000)
        if raw[-1] in ("B", "b"):
            return int(float(raw[:-1]) * 1_000_000_000)
        return int(float(raw))
    except (ValueError, AttributeError, IndexError):
        return None


def parse_row_lines(lines: list[str]) -> dict:
    """Parse the text lines from a video row into structured data.

    Observed row format (from TikTok Studio content table):
      [duration]     e.g. "00:21"
      [caption]      e.g. "Kanye West - Father Stretch..."
      [Pinned]       optional
      [date]         e.g. "May 8, 9:35 PM"  or  "Aug 4, 2025, 8:09 AM"
      [privacy]      e.g. "Everyone"
      [views]        e.g. "514" or "5.5M"
      [likes]        e.g. "54" or "580K"
      [comments]     e.g. "0" or "799"
    """
    result: dict = {
        "post_date": None,
        "views_raw": None,
        "likes_raw": None,
        "comments_raw": None,
    }

    # Work backwards from the end — last 3 numeric-ish values are comments, likes, views
    numeric_indices = []
    for i in range(len(lines) - 1, -1, -1):
        val = lines[i].strip().replace(",", "")
        if re.match(r"^[\d.]+[KkMmBb]?$", val):
            numeric_indices.append(i)
        if len(numeric_indices) >= 3:
            break

    numeric_indices.reverse()

    if len(numeric_indices) >= 3:
        result["views_raw"] = lines[numeric_indices[0]]
        result["likes_raw"] = lines[numeric_indices[1]]
        result["comments_raw"] = lines[numeric_indices[2]]

        # Date is usually 2 lines before the first numeric (skipping "Everyone"/privacy)
        date_search_end = numeric_indices[0]
        for i in range(date_search_end - 1, -1, -1):
            line = lines[i]
            if re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d", line):
                result["post_date"] = line
                break

    return result


# ── Storage ──────────────────────────────────────────────────────────────────

def store_video(conn: sqlite3.Connection, data: dict) -> None:
    video_id = data["video_id"]
    caption = data.get("caption", "")

    hashtags = None
    if caption:
        tags = re.findall(r"#\w+", caption)
        if tags:
            hashtags = json.dumps(tags)

    parsed = parse_row_lines(data.get("lines", []))

    conn.execute(
        """INSERT INTO videos (
            video_id, scraped_at, status,
            post_date, caption, hashtags, thumbnail_url, video_url,
            views_raw, likes_raw, comments_raw,
            views, likes, comments
        ) VALUES (?, ?, 'scraped', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(video_id) DO UPDATE SET
            scraped_at=excluded.scraped_at, status=excluded.status,
            post_date=excluded.post_date, caption=excluded.caption,
            hashtags=excluded.hashtags, thumbnail_url=excluded.thumbnail_url,
            video_url=excluded.video_url,
            views_raw=excluded.views_raw, likes_raw=excluded.likes_raw,
            comments_raw=excluded.comments_raw,
            views=excluded.views, likes=excluded.likes,
            comments=excluded.comments
        """,
        (
            video_id, _now(),
            parsed["post_date"], caption, hashtags,
            data.get("thumbnail_url"), data.get("video_url"),
            parsed["views_raw"], parsed["likes_raw"], parsed["comments_raw"],
            parse_number(parsed["views_raw"]),
            parse_number(parsed["likes_raw"]),
            parse_number(parsed["comments_raw"]),
        ),
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Export ───────────────────────────────────────────────────────────────────

def export_csv(conn: sqlite3.Connection, csv_path: Path) -> None:
    cursor = conn.execute(
        "SELECT * FROM videos WHERE status = 'scraped' ORDER BY post_date DESC"
    )
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)

    print(f"Exported {len(rows)} rows to {csv_path}")


# ── Scraping ─────────────────────────────────────────────────────────────────

async def scrape_content_table(page) -> list[dict]:
    """Scroll through TikTok Studio content table and extract all video data."""

    await page.goto(STUDIO_CONTENT_URL, timeout=PAGE_TIMEOUT, wait_until="load")
    await asyncio.sleep(8)

    if await _check_captcha(page):
        print("\n  CAPTCHA detected -- please solve it in the Chrome window.")
        input("  Press Enter after solving the CAPTCHA to continue...")
        await asyncio.sleep(2)

    # Find the scrollable container for the video list
    scroll_selector = await page.evaluate("""
        () => {
            const all = document.querySelectorAll('*');
            for (const el of all) {
                const style = window.getComputedStyle(el);
                if ((style.overflowY === 'auto' || style.overflowY === 'scroll') &&
                    el.scrollHeight > el.clientHeight + 200 &&
                    el.querySelector('a[href*="/video/"]')) {
                    // Tag it so we can find it again
                    el.setAttribute('data-scraper-scroll', 'true');
                    return true;
                }
            }
            return false;
        }
    """)

    all_videos: dict[str, dict] = {}
    no_change_streak = 0
    last_count = 0

    while no_change_streak < 5:
        # Extract videos currently visible in DOM
        batch = await page.evaluate(EXTRACT_VIDEOS_JS)
        for item in batch:
            vid = item["video_id"]
            if vid not in all_videos:
                all_videos[vid] = item

        if len(all_videos) == last_count:
            no_change_streak += 1
        else:
            no_change_streak = 0
            last_count = len(all_videos)

        print(f"  Found {len(all_videos)} videos so far...")

        # Scroll the container (or page if no container found)
        if scroll_selector:
            await page.evaluate("""
                () => {
                    const el = document.querySelector('[data-scraper-scroll]');
                    if (el) el.scrollTop = el.scrollHeight;
                }
            """)
        else:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

        await asyncio.sleep(random.uniform(1.5, 3.0))

    return list(all_videos.values())


async def _check_captcha(page) -> bool:
    url = page.url.lower()
    title = (await page.title()).lower()
    if "captcha" in url or "captcha" in title or "verify" in title:
        return True
    captcha_el = await page.query_selector("[class*='captcha'], [id*='captcha']")
    return captcha_el is not None


# ── Main ─────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("TikTok Analytics Scraper")
    print("-" * 45)

    print(f"Connecting to Chrome on {CDP_URL}...", end="  ", flush=True)
    try:
        pw = await async_playwright().start()
        browser = await pw.chromium.connect_over_cdp(CDP_URL)
    except Exception as e:
        print("FAILED")
        print(f"\nCould not connect to Chrome. Make sure Chrome is running with:")
        print(f'  chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\\chrome-debug-profile"')
        print(f"\nError: {e}")
        sys.exit(1)

    print("OK")

    context = browser.contexts[0]
    page = context.pages[0] if context.pages else await context.new_page()
    page.set_default_timeout(PAGE_TIMEOUT)

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    print(f"Database initialised: {DB_PATH.name}")

    log_started = _now()

    # Get already-scraped IDs for resume
    cursor = conn.execute("SELECT video_id FROM videos WHERE status = 'scraped'")
    already_done = {row[0] for row in cursor.fetchall()}

    print("\nCrawling content table from TikTok Studio...")
    try:
        all_videos = await scrape_content_table(page)
    except Exception as e:
        print(f"\nFailed to crawl content table: {e}")
        conn.close()
        await browser.close()
        await pw.stop()
        sys.exit(1)

    # Filter out already-scraped
    pending = [v for v in all_videos if v["video_id"] not in already_done]

    print(f"\nVideo list complete: {len(all_videos)} total")
    print(f"Already scraped:        {len(already_done)}")
    print(f"To scrape this session: {len(pending)}")

    if not pending:
        print("\nNothing new to scrape.")
        export_csv(conn, CSV_PATH)
        conn.close()
        await browser.close()
        await pw.stop()
        return

    # Store all pending videos
    print(f"\nStoring data...")
    print("-" * 45)

    scraped_count = 0
    failed_count = 0
    total = len(pending)

    for i, video_data in enumerate(pending, 1):
        vid = video_data["video_id"]
        try:
            store_video(conn, video_data)
            conn.commit()
            scraped_count += 1

            parsed = parse_row_lines(video_data.get("lines", []))
            views_str = parsed.get("views_raw", "?")
            print(f"[{i:>4}/{total}] + {vid}  --  {views_str} views")

        except Exception as e:
            failed_count += 1
            conn.execute(
                "INSERT INTO videos (video_id, status, error_message, scraped_at) "
                "VALUES (?, 'failed', ?, ?) "
                "ON CONFLICT(video_id) DO UPDATE SET status='failed', error_message=?, scraped_at=?",
                (vid, str(e), _now(), str(e), _now()),
            )
            conn.commit()
            print(f"[{i:>4}/{total}] X {vid}  --  FAILED: {e}")

    # Log scrape run
    conn.execute(
        "INSERT INTO scrape_log (started_at, finished_at, total_videos, scraped_count, failed_count, skipped_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (log_started, _now(), total, scraped_count, failed_count, 0),
    )
    conn.commit()

    print("\n" + "-" * 45)
    print("Scrape complete.")
    print(f"  Scraped:  {scraped_count}")
    print(f"  Failed:   {failed_count}")

    export_csv(conn, CSV_PATH)
    conn.close()
    await browser.close()
    await pw.stop()

    print(f"\nDone. Open {DB_PATH.name} in DB Browser for SQLite for analysis.")


if __name__ == "__main__":
    asyncio.run(main())
