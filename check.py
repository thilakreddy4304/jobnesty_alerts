#!/usr/bin/env python3
"""Check the Jobnesty dashboard for new jobs and push one ntfy alert per run.

  python check.py                     # normal run (what GitHub Actions does)
  python check.py --dry-run           # log in, scrape, print rows; no alert, seen.json untouched
  python check.py --fixture tests/fixture_dashboard.html --dry-run   # parse local HTML, no login
"""
import argparse
import json
import os
import re
import sys

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

try:
    from dotenv import load_dotenv
    load_dotenv()  # local runs only; variables already in the environment win
except ImportError:
    pass

BASE = "https://jobnesty-kikk.onrender.com"
LOGIN_URL = f"{BASE}/login"
DASHBOARD_URL = f"{BASE}/dashboard"
SEEN = "seen.json"
TIMEOUT_MS = 90_000  # Render free tier cold starts can take 30-60s
MAX_LISTED = 5

# These login selectors are guesses. Record the real ones with:
#   playwright codegen https://jobnesty-kikk.onrender.com/login
EMAIL_SELECTOR = 'input[type="email"]'
PASSWORD_SELECTOR = 'input[type="password"]'
SUBMIT_SELECTOR = 'button[type="submit"]'
ROW_SELECTOR = "tbody tr"

# Only alert once the resume is ready. Set to None to alert on every new row.
READY_STATUS = "completed"

EXTRACT_JS = """rows => rows.map(r => {
    const td = r.querySelectorAll('td');
    if (td.length < 6) return null;  // e.g. a "No jobs yet" placeholder row
    const link = td[0].querySelector('a');
    const dl = td[5].querySelector('a');
    return {
        company: (link ?? td[0]).innerText.trim(),
        job_url: link?.href ?? '',
        category: td[1].innerText.trim(),
        location: td[2].innerText.trim(),
        posted: td[3].innerText.trim(),
        status: td[4].innerText.trim().toLowerCase(),
        resume: dl?.getAttribute('href') ?? '',
    };
}).filter(Boolean)"""

PAGINATION_JS = """() => {
    if (document.querySelector('nav[aria-label*="pagination" i], [class*="pagination" i]')) return true;
    const labels = ['next', 'next page', 'load more', 'show more', '›', '»'];
    return [...document.querySelectorAll('button, a')]
        .some(e => labels.includes(e.innerText.trim().toLowerCase()));
}"""


class LoginRejected(Exception):
    pass


def env(name):
    value = os.environ.get(name)
    if not value:
        sys.exit(f"Missing environment variable {name} (set it in GitHub Secrets or .env)")
    return value


def extract(page):
    rows = page.eval_on_selector_all(ROW_SELECTOR, EXTRACT_JS)
    for r in rows:
        m = re.search(r"/api/resume/(\d+)", r["resume"])
        r["key"] = f"resume:{m.group(1)}" if m else r["job_url"]
    return rows, page.evaluate(PAGINATION_JS)


def scrape_once(browser, email, password):
    context = browser.new_context()
    page = context.new_page()
    page.set_default_timeout(TIMEOUT_MS)
    try:
        page.goto(LOGIN_URL)
        try:
            # Let Next.js hydrate first; submitting a raw form could put the password in a GET URL.
            page.wait_for_load_state("networkidle", timeout=30_000)
        except PlaywrightTimeout:
            pass
        page.fill(EMAIL_SELECTOR, email)
        page.fill(PASSWORD_SELECTOR, password)
        page.click(SUBMIT_SELECTOR)
        try:
            page.wait_for_url(lambda url: "/login" not in url)
        except PlaywrightTimeout:
            raise LoginRejected() from None
        if "/dashboard" not in page.url:
            page.goto(DASHBOARD_URL)
        page.wait_for_selector(ROW_SELECTOR)
        return extract(page)
    finally:
        context.close()


def scrape(email, password):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            for attempt in (1, 2):
                try:
                    return scrape_once(browser, email, password)
                except LoginRejected:
                    sys.exit("Still on /login after submitting: wrong credentials or login selectors "
                             "(see EMAIL_SELECTOR etc. at the top of check.py)")
                except PlaywrightTimeout as e:
                    if attempt == 2:
                        sys.exit(f"Timed out twice loading the site or dashboard table: {e}")
                    print("Timed out (Render cold start?), retrying once...")
        finally:
            browser.close()


def scrape_fixture(path):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        with open(path, encoding="utf-8") as f:
            page.set_content(f.read())
        result = extract(page)
        browser.close()
        return result


def is_ready(row):
    return READY_STATUS is None or row["status"] == READY_STATUS


def format_row(r):
    return f"{r['company']} - {r['category']}, {r['location']} ({r['posted']})"


def send_alert(new, topic):
    body = "\n".join(format_row(r) for r in new[:MAX_LISTED])
    if len(new) > MAX_LISTED:
        body += f"\n+{len(new) - MAX_LISTED} more"
    resp = requests.post(
        f"https://ntfy.sh/{topic}",
        data=body.encode("utf-8"),
        headers={
            "Title": f"{len(new)} new job(s) on Jobnesty",
            "Priority": "5",
            "Tags": "briefcase",
            "Click": DASHBOARD_URL,
        },
        timeout=30,
    )
    resp.raise_for_status()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print rows; no alert, no seen.json write")
    parser.add_argument("--fixture", help="parse this local HTML file instead of logging in")
    args = parser.parse_args()

    topic = None if args.dry_run else env("NTFY_TOPIC")
    if args.fixture:
        rows, paginated = scrape_fixture(args.fixture)
    else:
        rows, paginated = scrape(env("JN_EMAIL"), env("JN_PASSWORD"))

    if not rows:
        sys.exit("No job rows found on the dashboard: the login or table selector probably broke")
    if paginated:
        print("WARNING: the dashboard looks paginated. Only the first page is checked, "
              "so jobs that land beyond it will be missed.")

    first_run = not os.path.exists(SEEN)
    seen = set() if first_run else set(json.load(open(SEEN)))
    ready = [r for r in rows if r["key"] and is_ready(r)]
    new = list({r["key"]: r for r in ready if r["key"] not in seen}.values())

    print(f"{len(rows)} rows, {len(ready)} ready, {len(new)} new")
    if args.dry_run:
        for r in rows:
            mark = "NEW " if r in new else "    "
            print(f"{mark}[{r['status']}] {format_row(r)}  key={r['key']}")
        return

    if first_run:
        print(f"First run: recorded {len(ready)} jobs without alerting")
    elif new:
        send_alert(new, topic)
        print(f"Sent alert for {len(new)} new job(s)")

    with open(SEEN, "w") as f:
        json.dump(sorted(seen | {r["key"] for r in ready}), f, indent=1)
        f.write("\n")


if __name__ == "__main__":
    main()
