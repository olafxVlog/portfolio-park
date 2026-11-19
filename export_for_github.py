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
PAGES = [
    ("/", "index.html"),
    ("/?page_id=113", "oferta/index.html"),
    ("/?page_id=99", "moje-realizacje/index.html"),
    ("/?page_id=72", "o-mnie/index.html"),
    ("/?page_id=189", "zdjecia-z-planow/index.html"),
    ("/?page_id=74", "jak-dzialam/index.html"),
]
PAGE_ROUTES = {
    73: "index.html",
    113: "oferta/index.html",
    99: "moje-realizacje/index.html",
    72: "o-mnie/index.html",
    189: "zdjecia-z-planow/index.html",
    74: "jak-dzialam/index.html",
}
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
    if ";" in value or "*" in value:
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


def rewrite_page_links(source: str, from_file: Path) -> str:
    def replace(match: re.Match[str]) -> str:
        page_id = int(match.group(1))
        target = PAGE_ROUTES.get(page_id)
        if not target:
            return match.group(0)
        route_dir = (DOCS / target).parent.resolve()
        relative = os.path.relpath(route_dir, from_file.parent.resolve()).replace(os.sep, "/")
        if relative == ".":
            relative = "./"
        else:
            relative += "/"
        return relative + (match.group(2) or "")

    return re.sub(
        r"(?:https?://(?:localhost|127\.0\.0\.1):8080)?/\?page_id=(\d+)(#[^\"'<>\s]*)?",
        replace,
        source,
    )


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
                if parsed.scheme not in ("", "http", "https"):
                    continue
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
        html = rewrite_page_links(html, target)
        # Elementor's frontend CSS is emitted by WordPress's runtime, so it is
        # absent from static HTML. Load the downloaded local stylesheets here.
        if target == DOCS / "moje-realizacje/index.html":
            elementor_css = (
                '<link rel="stylesheet" href="../wp-content/uploads/elementor/css/base-desktop.css">'
                '<link rel="stylesheet" href="../wp-content/uploads/elementor/css/local-99-frontend-desktop.css">'
                '<link rel="stylesheet" href="../wp-content/uploads/elementor/css/local-99-frontend-mobile.css">'
                '<link rel="stylesheet" href="../wp-content/uploads/elementor/css/post-99.css">'
            )
            html = html.replace("</head>", elementor_css + "</head>")
        html = html.replace(
            "</head>",
            '<style id="static-navigation">'
            '.wp-block-navigation__responsive-container-open,.wp-block-navigation__responsive-container-close{display:none!important}'
            '.wp-block-navigation__responsive-container{display:block!important;position:static!important;width:auto!important;height:auto!important;max-height:none!important;opacity:1!important;visibility:visible!important;overflow:visible!important;background:transparent!important}'
            '.wp-block-navigation__responsive-container-content{display:block!important;visibility:visible!important}'
            '.wp-block-navigation__container{display:flex!important;flex-wrap:wrap!important;justify-content:center!important;gap:1rem!important}'
            '.portfolio-brand-nav{display:flex!important;flex-wrap:nowrap!important;justify-content:flex-start!important;align-items:center!important;gap:12px!important;overflow-x:auto!important;white-space:nowrap!important}'
            '.portfolio-brand-nav p{margin:0!important}'
            '.portfolio-brand-nav a{color:#d68cf1!important;text-decoration:none!important}'
            '@media(max-width:760px){.portfolio-brand-nav{gap:10px!important}.portfolio-brand-nav p{font-size:13px!important}}'
            '</style></head>',
        )
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
        target.write_text(re.sub(r"[ \t]+\n", "\n", html), encoding="utf-8")

    print(f"Created static pages and downloaded {len(seen)} WordPress assets into {DOCS}")


if __name__ == "__main__":
    main()
