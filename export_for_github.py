"""Build a static, shareable snapshot of the local WordPress portfolio."""

from __future__ import annotations

import os
import re
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
BASE = "http://127.0.0.1:8080"
PAGES = [("/", "index.html"), ("/?page_id=113", "oferta/index.html")]
ASSET_RE = re.compile(r"(?:https?://localhost:8080)?(/(?:wp-content|wp-includes)/[^\s\"'<>),;]+)")
CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "OlafxVlog portfolio snapshot"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def asset_path(value: str) -> str | None:
    value = urllib.parse.unquote(value.split("#", 1)[0].split("?", 1)[0])
    if not value.startswith(("/wp-content/", "/wp-includes/")):
        return None
    return value


def local_refs(source: str) -> set[str]:
    refs = set()
    for match in ASSET_RE.finditer(source):
        path = asset_path(match.group(1))
        if path:
            refs.add(path)
    return refs


def relative_url(path: str, from_file: Path) -> str:
    target = (DOCS / path.lstrip("/")).resolve()
    return os.path.relpath(target, from_file.parent.resolve()).replace(os.sep, "/")


def rewrite_asset_refs(source: str, from_file: Path) -> str:
    def replace(match: re.Match[str]) -> str:
        path = asset_path(match.group(1))
        return relative_url(path, from_file) if path else match.group(0)

    return ASSET_RE.sub(replace, source)


def main() -> None:
    DOCS.mkdir(exist_ok=True)
    fetched_pages: list[tuple[Path, str]] = []
    assets: set[str] = set()

    for route, output in PAGES:
        target = DOCS / output
        target.parent.mkdir(parents=True, exist_ok=True)
        html = fetch(BASE + route).decode("utf-8", "replace")
        assets.update(local_refs(html))
        fetched_pages.append((target, html))

    # Include every media file currently present in WordPress. The media directory
    # is copied from the running container below this script's invocation.
    queue = list(assets)
    seen: set[str] = set()
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        destination = DOCS / path.lstrip("/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = fetch(BASE + path)
        except Exception as exc:
            print(f"Skipping unavailable asset {path}: {exc}")
            continue
        destination.write_bytes(data)
        if destination.suffix.lower() == ".css":
            source = data.decode("utf-8", "replace")
            for _, value in CSS_URL_RE.findall(source):
                parsed = urllib.parse.urlparse(value)
                if parsed.netloc and parsed.netloc not in ("localhost:8080", "127.0.0.1:8080"):
                    continue
                ref = parsed.path if parsed.path.startswith("/") else urllib.parse.urljoin(path, parsed.path)
                ref = asset_path(ref)
                if ref and ref not in seen:
                    queue.append(ref)
            destination.write_text(rewrite_asset_refs(source, destination), encoding="utf-8")

    for target, html in fetched_pages:
        # The GitHub preview is static: strip WordPress runtime/API scripts and
        # metadata that would otherwise point back to the private localhost site.
        html = re.sub(r"<script\b[^>]*>.*?</script\s*>", "", html, flags=re.I | re.S)
        html = re.sub(r"<link\b[^>]*localhost:8080[^>]*>", "", html, flags=re.I)
        html = re.sub(r"https?://localhost:8080(/(?:wp-content|wp-includes)/[^\s\"'<>),;]+)",
                      lambda m: relative_url(asset_path(m.group(1)) or m.group(1), target), html)
        is_home = target == DOCS / "index.html"
        if is_home:
            html = html.replace('href="/?page_id=113"', 'href="./oferta/"')
            html = html.replace("href='/?page_id=113'", "href='./oferta/'")
            html = html.replace('href="/#', 'href="./#').replace("href='/#", "href='./#")
            html = html.replace('action="/#', 'action="./#').replace("action='/#", "action='./#")
            html = html.replace('href="/"', 'href="./"').replace("href='/'", "href='./'")
            html = html.replace('action="/"', 'action="./"').replace("action='/'", "action='./'")
            html = html.replace("http://localhost:8080/", "./")
        else:
            html = html.replace('href="/?page_id=113"', 'href="./"')
            html = html.replace("href='/?page_id=113'", "href='./'")
            html = html.replace('href="/#', 'href="../#').replace("href='/#", "href='../#")
            html = html.replace('action="/#', 'action="../#').replace("action='/#", "action='../#")
            html = html.replace('href="/"', 'href="../"').replace("href='/'", "href='../'")
            html = html.replace('action="/"', 'action="../"').replace("action='/'", "action='../'")
            html = html.replace("http://localhost:8080/", "../")
        if is_home:
            html = html.replace('<form action="./#wpcf7-', '<form onsubmit="return false" action="./#wpcf7-')
            html = html.replace(
                '<input class="wpcf7-form-control wpcf7-submit has-spinner" type="submit" value="Wyślij" />',
                '<a class="wpcf7-form-control wpcf7-submit" href="https://www.instagram.com/olafxvlog/" '
                'target="_blank" rel="noopener">Napisz na Instagramie ↗</a>',
            )
            html = html.replace(
                '<div class="wpcf7-response-output"',
                '<p class="wpcf7-static-note">To statyczny podgląd — formularz nie wysyła wiadomości. '
                'Skontaktuj się ze mną przez Instagram.</p><div class="wpcf7-response-output"',
            )
        target.write_text(html, encoding="utf-8")

    print(f"Created static pages and downloaded {len(seen)} WordPress assets into {DOCS}")


if __name__ == "__main__":
    main()
