"""Build a static, shareable snapshot of the local WordPress portfolio."""

from __future__ import annotations

import os
import html
import json
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
MENU_ITEMS = [
    ("Start", 73),
    ("Moje realizacje", 99),
    ("O mnie", 72),
    ("Zdjęcia z planów", 189),
    ("Jak działam", 74),
    ("Oferta", 113),
]
ASSET_RE = re.compile(r"(?:https?://localhost:8080)?(/(?:wp-content|wp-includes)/[^\s\"'<>),;]+)")
CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)
YOUTUBE_BLOCK_RE = re.compile(
    r'<div(?P<attrs>[^>]*\be-youtube-base\b[^>]*)>\s*</div>', re.I | re.S
)


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


def render_youtube_embeds(source: str) -> str:
    """Replace Elementor's JS-rendered YouTube placeholders with static iframes."""
    def replace(match: re.Match[str]) -> str:
        attrs = match.group("attrs")
        settings_match = re.search(r'data-settings="([^"]*)"', attrs)
        if not settings_match:
            return match.group(0)
        try:
            settings = json.loads(html.unescape(settings_match.group(1)))
        except (ValueError, TypeError):
            return match.group(0)
        source_url = settings.get("source", "")
        video_match = re.search(r"(?:youtu\.be/|youtube\.com/(?:shorts/|embed/|watch\\?v=))([A-Za-z0-9_-]{6,})", source_url)
        if not video_match:
            return match.group(0)
        video_id = video_match.group(1)
        title = html.escape(f"Film OlafxVlog {video_id}", quote=True)
        return (
            f'<div{attrs}>'
            f'<iframe src="https://www.youtube-nocookie.com/embed/{video_id}" '
            f'title="{title}" loading="lazy" allow="accelerometer; autoplay; clipboard-write; '
            'encrypted-media; gyroscope; picture-in-picture; web-share" allowfullscreen></iframe>'
            '</div>'
        )

    return YOUTUBE_BLOCK_RE.sub(replace, source)


def render_site_header(from_file: Path) -> str:
    links = []
    for label, page_id in MENU_ITEMS:
        route_dir = (DOCS / PAGE_ROUTES[page_id]).parent.resolve()
        relative = os.path.relpath(route_dir, from_file.parent.resolve()).replace(os.sep, "/")
        href = "./" if relative == "." else relative.rstrip("/") + "/"
        links.append(f'<a href="{href}">{html.escape(label)}</a>')
    link_html = "".join(links)
    return (
        '<header class="ov-site-header">'
        '<a class="ov-site-brand" href="' + ("./" if from_file == DOCS / "index.html" else "../") + '">OlafxVlog</a>'
        '<nav class="ov-desktop-navigation" aria-label="Menu główne">' + link_html + '</nav>'
        '<details class="ov-mobile-navigation">'
        '<summary aria-label="Pokaż menu"><span aria-hidden="true">☰</span> Menu</summary>'
        '<nav class="ov-mobile-links" aria-label="Menu główne">' + link_html + '</nav>'
        '</details></header>'
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
        if target == DOCS / "moje-realizacje/index.html":
            html = render_youtube_embeds(html)
        # Elementor prints its layout CSS through WordPress at runtime. These
        # files need to be linked explicitly in the static GitHub Pages export.
        elementor_page_id = next(
            (page_id for page_id, route_file in PAGE_ROUTES.items() if DOCS / route_file == target),
            None,
        )
        if elementor_page_id is not None:
            css_files = ["post-49.css", "base-desktop.css", "base-mobile.css", f"post-{elementor_page_id}.css"]
            if elementor_page_id == 99:
                css_files.extend(["local-99-frontend-desktop.css", "local-99-frontend-mobile.css"])
            css_dir = "../wp-content/uploads/elementor/css/" if target.parent != DOCS else "wp-content/uploads/elementor/css/"
            elementor_css = "".join(
                f'<link rel="stylesheet" href="{css_dir}{name}">' for name in css_files
            )
            html = html.replace("</head>", elementor_css + "</head>")
        html = html.replace(
            "</head>",
            '<style id="static-navigation">'
            '.wp-block-navigation__responsive-container-open,.wp-block-navigation__responsive-container-close{display:none!important}'
            '.wp-block-navigation__responsive-container{display:block!important;position:static!important;width:auto!important;height:auto!important;max-height:none!important;opacity:1!important;visibility:visible!important;overflow:visible!important;background:transparent!important}'
            '.wp-block-navigation__responsive-container-content{display:block!important;visibility:visible!important}'
            '.wp-block-navigation__container{display:flex!important;flex-wrap:wrap!important;justify-content:center!important;gap:1rem!important}'
            '.portfolio-brand-nav,body:not(.page-id-73) .wp-block-group:has(> .portfolio-brand-nav),.wp-block-group:has(> nav.wp-block-navigation){display:none!important}'
            '.ov-site-header{position:relative;z-index:100;display:flex;align-items:center;justify-content:space-between;gap:24px;width:100%;min-height:64px;padding:12px 24px;box-sizing:border-box;background:#17151c;color:#d68cf1;font-family:inherit}'
            'body.page-id-73 .ov-site-header{position:absolute;top:0;left:0;background:transparent}'
            '.ov-site-brand{flex:0 0 auto;color:#d68cf1!important;text-decoration:none!important;font-size:16px;font-weight:800;letter-spacing:.5px}'
            '.ov-desktop-navigation{display:flex;align-items:center;justify-content:flex-end;gap:clamp(10px,1.7vw,22px);min-width:0;white-space:nowrap}'
            '.ov-desktop-navigation a,.ov-mobile-links a{color:#d68cf1!important;text-decoration:none!important;font-size:13px;font-weight:600;line-height:1.35}'
            '.ov-desktop-navigation a:hover,.ov-mobile-links a:hover{color:#fff!important}'
            '.ov-mobile-navigation{display:none;position:relative;margin-left:auto}'
            '.ov-mobile-navigation summary{display:flex;align-items:center;justify-content:center;gap:8px;min-height:44px;padding:0 15px;border:1px solid #56445f;border-radius:999px;background:#292631;color:#f5eafb;font-size:14px;font-weight:700;list-style:none;cursor:pointer}'
            '.ov-mobile-navigation summary::-webkit-details-marker{display:none}'
            '.ov-mobile-links{position:absolute;top:calc(100% + 10px);right:0;z-index:110;display:flex;flex-direction:column;gap:2px;width:min(270px,calc(100vw - 32px));padding:9px;border:1px solid #393440;border-radius:17px;background:#211e27;box-shadow:0 18px 46px rgba(0,0,0,.4)}'
            '.ov-mobile-links a{display:flex;align-items:center;min-height:46px;padding:0 14px;border-radius:10px;font-size:15px}'
            '.ov-mobile-links a:hover{background:#302c37}'
            '.ov-form-status{margin:12px 0 0;color:#d7f6de;font-size:14px;line-height:1.5}'
            '.portfolio-brand-nav{display:flex!important;flex-wrap:nowrap!important;justify-content:flex-start!important;align-items:center!important;gap:12px!important;overflow-x:auto!important;white-space:nowrap!important}'
            '.portfolio-brand-nav p{margin:0!important}'
            '.portfolio-brand-nav a{color:#d68cf1!important;text-decoration:none!important}'
            '.elementor-73 .elementor-element-36d092e{width:100%;margin:22px auto 30px;padding:0 20px;box-sizing:border-box}'
            '.elementor-73 .elementor-social-icons-wrapper{display:flex!important;flex-flow:row wrap!important;justify-content:center!important;align-items:center!important;gap:12px!important}'
            '.elementor-73 .elementor-social-icons-wrapper .elementor-grid-item{display:block!important;flex:0 0 auto!important}'
            '.elementor-73 .elementor-social-icons-wrapper .elementor-screen-only{position:absolute!important;width:1px!important;height:1px!important;padding:0!important;margin:-1px!important;overflow:hidden!important;clip:rect(0,0,0,0)!important;white-space:nowrap!important;border:0!important}'
            '.elementor-73 .elementor-social-icons-wrapper .elementor-icon{display:inline-flex!important;align-items:center!important;justify-content:center!important;width:46px!important;height:46px!important;padding:0!important;border-radius:50%!important;background:#292631!important;color:#f4eff8!important;transition:transform .2s ease,background .2s ease}'
            '.elementor-73 .elementor-social-icons-wrapper .elementor-icon:hover{transform:translateY(-3px);background:#8c4bd1!important}'
            '.elementor-73 .elementor-social-icons-wrapper svg{display:block!important;width:20px!important;height:20px!important;max-width:20px!important;max-height:20px!important;fill:currentColor!important}'
            '.elementor-73 .elementor-element-06c989a{width:min(100% - 40px,680px)!important;margin:0 auto 48px!important}'
            '.elementor-73 .elementor-element-06c989a .wpcf7{padding:28px!important;border:1px solid #393440!important;border-radius:22px!important;background:#211e27!important;box-shadow:0 18px 50px rgba(0,0,0,.22)!important}'
            '.elementor-73 .elementor-element-06c989a .wpcf7 form p{margin:0 0 17px!important}'
            '.elementor-73 .elementor-element-06c989a .wpcf7 form label{display:block!important;color:#eee8f2!important;font-size:14px!important;font-weight:600!important;line-height:1.55!important}'
            '.elementor-73 .elementor-element-06c989a .wpcf7-form-control-wrap{display:block!important;margin-top:7px!important}'
            '.elementor-73 .elementor-element-06c989a .wpcf7 input:not([type=submit]),.elementor-73 .elementor-element-06c989a .wpcf7 textarea{display:block!important;width:100%!important;max-width:100%!important;box-sizing:border-box!important;padding:13px 15px!important;border:1px solid #4a4453!important;border-radius:11px!important;background:#302c37!important;color:#fff!important;font:inherit!important;outline:none!important;transition:border-color .2s ease,box-shadow .2s ease}'
            '.elementor-73 .elementor-element-06c989a .wpcf7 input:focus,.elementor-73 .elementor-element-06c989a .wpcf7 textarea:focus{border-color:#bd75eb!important;box-shadow:0 0 0 3px rgba(189,117,235,.18)!important}'
            '.elementor-73 .elementor-element-06c989a .wpcf7 textarea{min-height:145px!important;resize:vertical!important}'
            '.elementor-73 .elementor-element-06c989a .wpcf7 input[type=submit]{display:inline-flex!important;align-items:center!important;justify-content:center!important;width:auto!important;min-width:150px!important;padding:13px 24px!important;border:0!important;border-radius:999px!important;background:#9652db!important;color:white!important;font-weight:700!important;cursor:pointer!important;transition:transform .2s ease,background .2s ease}'
            '.elementor-73 .elementor-element-06c989a .wpcf7 input[type=submit]:hover{transform:translateY(-2px);background:#aa65eb!important}'
            '.elementor-73 .elementor-element-06c989a .wpcf7 .wpcf7-response-output{color:#eee8f2!important}'
            '.elementor-99 .e-youtube-base{display:inline-block!important;vertical-align:top;width:500px;max-width:calc(100vw - 48px);height:auto!important;aspect-ratio:16/9;margin:10px;overflow:hidden}'
            '.elementor-99 .e-youtube-base iframe{display:block;width:100%;height:100%;border:0}'
            '.elementor-99 .e-235416d-37e6544,.elementor-99 .e-8392875-91f4352,.elementor-99 .e-40be9d1-95b2715,.elementor-99 .e-2113d0b-c2fb46c,.elementor-99 .e-3a06204-0a8653b{width:250px;aspect-ratio:9/16}'
            '@media(max-width:760px){.portfolio-brand-nav{gap:10px!important}.portfolio-brand-nav p{font-size:13px!important}}'
            '@media(max-width:767px){.elementor-99 .e-youtube-base{width:300px;max-width:calc(100vw - 48px);margin:8px auto;display:block!important}.elementor-99 .e-235416d-37e6544,.elementor-99 .e-8392875-91f4352,.elementor-99 .e-40be9d1-95b2715,.elementor-99 .e-2113d0b-c2fb46c,.elementor-99 .e-3a06204-0a8653b{width:220px}}'
            '@media(max-width:600px){.elementor-73 .elementor-element-06c989a{width:calc(100% - 32px)!important}.elementor-73 .elementor-element-06c989a .wpcf7{padding:21px 17px!important;border-radius:18px!important}.elementor-73 .elementor-social-icons-wrapper{gap:10px!important}.elementor-73 .elementor-social-icons-wrapper .elementor-icon{width:44px!important;height:44px!important}}'
            '@media(max-width:860px){.ov-site-header{min-height:62px;padding:10px 16px;gap:12px}.ov-desktop-navigation{display:none!important}.ov-mobile-navigation{display:block!important}.wp-block-buttons{display:flex!important;flex-flow:row wrap!important;align-items:center!important;gap:12px!important}.wp-block-buttons>.wp-block-button{flex:0 1 auto!important;width:auto!important;max-width:100%!important;margin:0!important}.wp-block-button__link{display:inline-flex!important;align-items:center!important;justify-content:center!important;max-width:100%!important;min-height:46px;box-sizing:border-box!important;white-space:normal!important;overflow-wrap:anywhere;line-height:1.35!important;text-align:center!important;padding:12px 18px!important}.elementor .elementor-button-wrapper{display:flex!important;flex-flow:row wrap!important;align-items:center!important;gap:12px!important;max-width:100%}.elementor .elementor-button{display:inline-flex!important;align-items:center!important;justify-content:center!important;width:auto!important;max-width:100%!important;min-height:46px;box-sizing:border-box!important;white-space:normal!important;overflow-wrap:anywhere;line-height:1.35!important;text-align:center!important;padding:12px 18px!important}.elementor .elementor-element{min-width:0}.elementor .e-con,.elementor .e-con-inner{max-width:100%;box-sizing:border-box}.elementor img,.wp-block-image img{max-width:100%;height:auto}.wp-site-blocks{overflow-x:clip}}'
            """@media(max-width:767px){body.page-id-74 .elementor-74 .elementor-element-5502da81{width:100%!important;max-width:100%!important}body.page-id-74 .wp-block-group[style*="padding: 56px 24px 56px"]{padding:38px 20px 26px!important}body.page-id-74 .wp-block-group[style*="background-color: #111116"]{padding:34px 16px!important;background:#17151c!important}body.page-id-74 .wp-block-columns{display:grid!important;grid-template-columns:minmax(0,1fr)!important;gap:14px!important;width:100%!important;max-width:620px!important;box-sizing:border-box!important;margin:0 auto 14px!important;padding:0!important}body.page-id-74 .wp-block-column{display:block!important;width:100%!important;min-width:0!important;max-width:100%!important;box-sizing:border-box!important;padding:0!important;margin:0!important}body.page-id-74 .wp-block-column>.wp-block-group[style*="#24212b"]{width:100%!important;max-width:100%!important;min-width:0!important;box-sizing:border-box!important;padding:20px!important;border:1px solid #3a3542!important;border-left:3px solid #b86ce3!important;border-radius:16px!important;background:#24212b!important;box-shadow:0 8px 24px rgba(0,0,0,.16)}body.page-id-74 .wp-block-column>.wp-block-group[style*="#24212b"]>p:first-child{margin:0 0 8px!important;color:#df9af5!important;font-size:11px!important;letter-spacing:1.5px!important;line-height:1.35!important}body.page-id-74 .wp-block-column>.wp-block-group[style*="#24212b"] h3{margin:0 0 10px!important;font-size:clamp(20px,5.5vw,24px)!important;line-height:1.22!important;letter-spacing:-.02em!important;overflow-wrap:anywhere!important;text-transform:none!important}body.page-id-74 .wp-block-column>.wp-block-group[style*="#24212b"] p:last-child{margin:0!important;color:#e1dde6!important;font-size:15px!important;line-height:1.6!important}body.page-id-74 .wp-block-group h1{font-size:clamp(40px,10vw,58px)!important;line-height:1.08!important;letter-spacing:-.03em!important}body.page-id-74 .wp-block-group p{overflow-wrap:break-word}body.page-id-74 .wp-block-buttons{display:grid!important;grid-template-columns:minmax(0,1fr)!important;width:min(100%,380px)!important;gap:10px!important;margin-left:auto!important;margin-right:auto!important}body.page-id-74 .wp-block-buttons>.wp-block-button,body.page-id-74 .wp-block-buttons .wp-block-button__link{width:100%!important;max-width:100%!important}body.page-id-74 .wp-block-buttons .wp-block-button__link{min-height:48px!important}"""
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
            # GitHub Pages cannot run WordPress/PHP handlers. Submit this form
            # through FormSubmit's hosted email endpoint instead.
            def configure_contact_form(match: re.Match[str]) -> str:
                attrs = re.sub(r'\s(?:action|method|onsubmit|novalidate)="[^"]*"', '', match.group(1))
                return (
                    '<form' + attrs
                    + ' action="https://formsubmit.co/olafjatkowski@wp.pl" method="POST">'
                )

            html = re.sub(
                r'<form(?=[^>]*class="[^"]*\bwpcf7-form\b[^"]*")([^>]*)>',
                configure_contact_form,
                html,
                count=1,
            )
            html = re.sub(
                r'<fieldset class="hidden-fields-container">.*?</fieldset>',
                '<fieldset class="hidden-fields-container">'
                '<input type="hidden" name="_subject" value="Nowa wiadomość z portfolio OlafxVlog" />'
                '<input type="hidden" name="_next" value="https://olafxvlog.github.io/portfolio-park/dziekuje/" />'
                '<input type="text" name="_honey" tabindex="-1" autocomplete="off" '
                'style="position:absolute;left:-9999px" />'
                '</fieldset>',
                html,
                count=1,
                flags=re.S,
            )
            html = html.replace('name="your-name"', 'name="name"')
            html = html.replace('name="your-email"', 'name="email"')
            html = html.replace('name="your-subject"', 'name="subject"')
            html = html.replace('name="your-message"', 'name="message"')
            html = html.replace('name="name" />', 'name="name" required />')
            html = html.replace('name="email" />', 'name="email" required />')
            html = html.replace('name="subject" />', 'name="subject" required />')
        site_header = render_site_header(target)
        html = re.sub(r'(<body\b[^>]*>)', lambda match: match.group(1) + site_header, html, count=1)
        if is_home:
            ajax_script = """<script>
document.addEventListener('DOMContentLoaded',function(){
  var form=document.querySelector('.wpcf7-form');
  if(!form)return;
  form.addEventListener('submit',function(event){
    event.preventDefault();
    var button=form.querySelector('[type=submit]');
    var original=button?button.value:'';
    if(button){button.disabled=true;button.value='Wysyłam wiadomość…';}
    var status=document.createElement('p');
    status.className='ov-form-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');
    status.textContent='Wysyłam wiadomość…';form.appendChild(status);
    var payload=Object.fromEntries(new FormData(form).entries());
    fetch('https://formsubmit.co/ajax/olafjatkowski@wp.pl',{method:'POST',headers:{'Accept':'application/json','Content-Type':'application/json'},body:JSON.stringify(payload)})
      .then(function(response){return response.json().then(function(data){if(!response.ok||data.success===false)throw new Error('send failed');return data;});})
      .then(function(){status.textContent='Wiadomość została przyjęta. Dziękuję za kontakt!';form.reset();setTimeout(function(){window.location.href='https://olafxvlog.github.io/portfolio-park/dziekuje/';},900);})
      .catch(function(){status.remove();if(button){button.disabled=false;button.value=original;}form.submit();});
  });
});
</script>"""
            html = html.replace("</body>", ajax_script + "</body>")
        target.write_text(re.sub(r"[ \t]+\n", "\n", html), encoding="utf-8")

    thank_you = DOCS / "dziekuje/index.html"
    thank_you.parent.mkdir(parents=True, exist_ok=True)
    thank_you.write_text("""<!doctype html>
<html lang="pl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#17151c"><title>Dziękuję za wiadomość · OlafxVlog</title>
<style>*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:#17151c;color:#f7f3fa;font:16px/1.6 'DM Sans',Arial,sans-serif}.card{width:min(100%,620px);padding:clamp(28px,7vw,56px);border:1px solid #393440;border-radius:26px;background:#211e27;text-align:center;box-shadow:0 22px 70px #0005}.mark{display:grid;place-items:center;width:62px;height:62px;margin:0 auto 24px;border-radius:50%;background:#9652db;font-size:30px}p.kicker{color:#d68cf1;font-size:12px;font-weight:800;letter-spacing:.2em;text-transform:uppercase}h1{margin:10px 0 14px;font-size:clamp(34px,7vw,54px);line-height:1.08}p{color:#d2cbd8}.button{display:inline-flex;margin-top:18px;padding:13px 23px;border-radius:999px;background:#9652db;color:white;text-decoration:none;font-weight:700}.button:hover{background:#aa65eb}</style></head>
<body><main class="card"><div class="mark" aria-hidden="true">✓</div><p class="kicker">OlafxVlog · kontakt</p><h1>Dziękuję za wiadomość!</h1><p>Wiadomość została wysłana. Odezwę się do Ciebie najszybciej, jak to możliwe.</p><a class="button" href="../">Wróć do portfolio</a></main></body></html>""", encoding="utf-8")

    print(f"Created static pages and downloaded {len(seen)} WordPress assets into {DOCS}")


if __name__ == "__main__":
    main()
