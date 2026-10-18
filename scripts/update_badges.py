#!/usr/bin/env python3
"""Generate badges/stars.svg and badges/followers.svg from the GitHub REST API.

Standard library only. On any API error the script exits non-zero *before*
touching the existing badges, so a failed run never overwrites good SVGs.

Env:
  GITHUB_USER   account to count (default: GITHUB_REPOSITORY_OWNER or warren-wzw)
  GITHUB_TOKEN  optional; raises the rate limit (Actions provides it)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

API = "https://api.github.com"
USER = os.environ.get("GITHUB_USER") or os.environ.get("GITHUB_REPOSITORY_OWNER") or "warren-wzw"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT_DIR = Path(__file__).resolve().parent.parent / "badges"

# GitHub mark (Simple Icons, CC0) in whitesmoke, identical to Shields' logo=github.
GITHUB_LOGO = (
    "PHN2ZyBmaWxsPSJ3aGl0ZXNtb2tlIiByb2xlPSJpbWciIHZpZXdCb3g9IjAgMCAyNCAyNCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48dGl0bGU+R2l0SHViPC90aXRsZT48cGF0aCBkPSJNMTIgLjI5N2MtNi42MyAwLTEyIDUuMzczLTEyIDEyIDAgNS4zMDMgMy40MzggOS44IDguMjA1IDExLjM4NS42LjExMy44Mi0uMjU4LjgyLS41NzcgMC0uMjg1LS4wMS0xLjA0LS4wMTUtMi4wNC0zLjMzOC43MjQtNC4wNDItMS42MS00LjA0Mi0xLjYxQzQuNDIyIDE4LjA3IDMuNjMzIDE3LjcgMy42MzMgMTcuN2MtMS4wODctLjc0NC4wODQtLjcyOS4wODQtLjcyOSAxLjIwNS4wODQgMS44MzggMS4yMzYgMS44MzggMS4yMzYgMS4wNyAxLjgzNSAyLjgwOSAxLjMwNSAzLjQ5NS45OTguMTA4LS43NzYuNDE3LTEuMzA1Ljc2LTEuNjA1LTIuNjY1LS4zLTUuNDY2LTEuMzMyLTUuNDY2LTUuOTMgMC0xLjMxLjQ2NS0yLjM4IDEuMjM1LTMuMjItLjEzNS0uMzAzLS41NC0xLjUyMy4xMDUtMy4xNzYgMCAwIDEuMDA1LS4zMjIgMy4zIDEuMjMuOTYtLjI2NyAxLjk4LS4zOTkgMy0uNDA1IDEuMDIuMDA2IDIuMDQuMTM4IDMgLjQwNSAyLjI4LTEuNTUyIDMuMjg1LTEuMjMgMy4yODUtMS4yMy42NDUgMS42NTMuMjQgMi44NzMuMTIgMy4xNzYuNzY1Ljg0IDEuMjMgMS45MSAxLjIzIDMuMjIgMCA0LjYxLTIuODA1IDUuNjI1LTUuNDc1IDUuOTIuNDIuMzYuODEgMS4wOTYuODEgMi4yMiAwIDEuNjA2LS4wMTUgMi44OTYtLjAxNSAzLjI4NiAwIC4zMTUuMjEuNjkuODI1LjU3QzIwLjU2NSAyMi4wOTIgMjQgMTcuNTkyIDI0IDEyLjI5N2MwLTYuNjI3LTUuMzczLTEyLTEyLTEyIi8+PC9zdmc+"
)

# Text widths (px) as measured from Shields' for-the-badge output
# (Verdana 10px, letter-spacing included). Labels are fixed strings.
LABEL_WIDTH = {"STARS": 39.25, "FOLLOWERS": 73.25}
VALUE_CHAR_WIDTH = {".": 5.25, "M": 10.25}
DEFAULT_CHAR_WIDTH = 8.25  # digits, K
PAD = 12
LOGO_X, LOGO_SIZE, LOGO_GAP = 9, 14, 6


def api_get(path):
    """GET a JSON resource, retrying transient failures and waiting out rate limits."""
    url = path if path.startswith("http") else f"{API}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"{USER}-badge-updater",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    last_err = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as resp:
                return json.load(resp), resp.headers
        except urllib.error.HTTPError as e:
            last_err = e
            remaining = e.headers.get("X-RateLimit-Remaining")
            if e.code in (403, 429) and (remaining == "0" or e.headers.get("Retry-After")):
                reset = int(e.headers.get("X-RateLimit-Reset", "0"))
                wait = int(e.headers.get("Retry-After") or max(reset - time.time(), 0) + 1)
                if wait > 120:
                    raise RuntimeError(f"rate limited for {wait}s on {url}") from e
                time.sleep(wait)
                continue
            if e.code < 500:
                raise RuntimeError(f"HTTP {e.code} on {url}: {e.read()[:200]!r}") from e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
        time.sleep(2 ** attempt)
    raise RuntimeError(f"request failed after retries: {url}: {last_err}")


def fetch_followers():
    data, _ = api_get(f"/users/{USER}")
    followers = data.get("followers")
    if not isinstance(followers, int) or followers < 0:
        raise RuntimeError(f"unexpected followers value: {followers!r}")
    return followers


def fetch_total_stars():
    """Sum stargazers over every public repo owned by USER, following all pages."""
    total, count, page = 0, 0, 1
    while True:
        repos, _ = api_get(f"/users/{USER}/repos?type=owner&per_page=100&page={page}")
        if not isinstance(repos, list):
            raise RuntimeError(f"unexpected repos payload on page {page}")
        for repo in repos:
            total += int(repo["stargazers_count"])
        count += len(repos)
        if len(repos) < 100:
            break
        page += 1
    expected, _ = api_get(f"/users/{USER}")
    if count != expected.get("public_repos", count):
        raise RuntimeError(f"repo count mismatch: listed {count}, profile says {expected.get('public_repos')}")
    return total, count


def metric(n):
    """Shields-style compact number: 999, 1.2K, 12K, 1.5M."""
    if n < 1000:
        return str(n)
    for div, suffix in ((10**3, "K"), (10**6, "M"), (10**9, "B")):
        v = n / div
        s = f"{v:.1f}" if v < 9.95 else f"{round(v)}"
        if float(s) < 1000 or suffix == "B":
            return s.removesuffix(".0") + suffix


def render(label, value, color):
    label_w = LABEL_WIDTH[label]
    value_w = sum(VALUE_CHAR_WIDTH.get(c, DEFAULT_CHAR_WIDTH) for c in value)
    left = LOGO_X + LOGO_SIZE + LOGO_GAP + label_w + PAD
    right = value_w + PAD * 2
    width = left + right
    label_x = (LOGO_X + LOGO_SIZE + LOGO_GAP + label_w / 2) * 10
    value_x = (left + right / 2) * 10
    title = escape(f"{label}: {value}")
    lbl, val = escape(label), escape(value)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:g}" height="28" role="img" aria-label="{title}">'
        f"<title>{title}</title>"
        f'<g shape-rendering="crispEdges"><rect width="{left:g}" height="28" fill="#555"/>'
        f'<rect x="{left:g}" width="{right:g}" height="28" fill="{color}"/></g>'
        f'<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" '
        f'text-rendering="geometricPrecision" font-size="100">'
        f'<image x="{LOGO_X}" y="7" width="{LOGO_SIZE}" height="{LOGO_SIZE}" href="data:image/svg+xml;base64,{GITHUB_LOGO}"/>'
        f'<text transform="scale(.1)" x="{label_x:g}" y="175" textLength="{label_w * 10:g}">{lbl}</text>'
        f'<text transform="scale(.1)" x="{value_x:g}" y="175" textLength="{value_w * 10:g}" font-weight="bold">{val}</text>'
        f"</g></svg>\n"
    )


def main():
    try:
        followers = fetch_followers()
        stars, repo_count = fetch_total_stars()
    except Exception as e:  # leave existing badges untouched
        print(f"::error::badge update aborted, existing SVGs kept: {e}", file=sys.stderr)
        return 1

    print(f"user={USER} repos={repo_count} stars={stars} followers={followers}")
    OUT_DIR.mkdir(exist_ok=True)
    for name, svg in (
        ("stars.svg", render("STARS", metric(stars), "#f39c12")),
        ("followers.svg", render("FOLLOWERS", metric(followers), "#2eb85c")),
    ):
        path = OUT_DIR / name
        if path.exists() and path.read_text(encoding="utf-8") == svg:
            continue
        tmp = path.with_suffix(".svg.tmp")
        tmp.write_text(svg, encoding="utf-8")
        tmp.replace(path)
        print(f"updated {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
