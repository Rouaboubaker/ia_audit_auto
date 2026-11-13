"""Moteur d'analyse : Playwright visite le site, puis checks.py applique les règles (version de règles du dossier)."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urldefrag, urlparse

from . import checks
from .models import Finding, Rules

CHROME_CANDIDATES = [os.environ.get("CHROME_PATH", ""), "/usr/bin/google-chrome",
                     "/usr/bin/chromium", "/usr/bin/chromium-browser"]
SKIP_EXT = (".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".zip", ".doc", ".docx",
            ".xls", ".xlsx", ".ppt", ".pptx", ".mp3", ".mp4", ".css", ".js", ".xml", ".ico")
PAGE_TIMEOUT_MS = 20000

EXTRACT_JS = r"""
() => {
  const sel = el => { let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id; else if (el.classList.length) s += '.' + [...el.classList].slice(0, 2).join('.');
    return s; };
  const visible = el => { const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
    const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const SKIP = ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'OPTION'];
  const texts = [];
  for (const el of document.body.querySelectorAll('*')) {
    if (SKIP.includes(el.tagName)) continue;
    const own = [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ')
                  .replace(/\s+/g, ' ').trim();
    if (own.length < 2 || !visible(el)) continue;
    const cs = getComputedStyle(el);
    const layers = []; let n = el;
    while (n && n.nodeType === 1) {
      const c = getComputedStyle(n);
      layers.push({color: c.backgroundColor, img: !!c.backgroundImage && c.backgroundImage !== 'none'});
      n = n.parentElement;
    }
    texts.push({sel: sel(el), text: own.slice(0, 40), color: cs.color,
                size: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight) || 400, layers});
  }
  const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].filter(visible)
    .map(h => ({level: +h.tagName[1], text: h.textContent.replace(/\s+/g, ' ').trim().slice(0, 40)}));
  const links = [...document.querySelectorAll('a[href]')].map(a => a.href);
  return {texts, headings, links};
}
"""


def _find_chrome() -> str | None:
    return next((p for p in CHROME_CANDIDATES if p and Path(p).exists()), None)


def page_label(url: str) -> str:
    """Chemin de la page (sans le nom du site) : '/', '/contact?id=2'."""
    u = urlparse(url)
    return (u.path or "/") + (f"?{u.query}" if u.query else "")


def select_links(start_url: str, links: list[str], limit: int) -> list[str]:
    """Pages du même site (même schéma et même domaine), sans doublon, sans fichiers, hors page de départ."""
    start = urlparse(start_url)

    def norm(u: str) -> str:
        return urldefrag(u)[0].rstrip("/")

    seen = {norm(start_url)}
    out = []
    for link in links:
        u = urlparse(link)
        if (u.scheme, u.netloc) != (start.scheme, start.netloc) or u.path.lower().endswith(SKIP_EXT):
            continue
        n = norm(link)
        if n in seen:
            continue
        seen.add(n)
        out.append(urldefrag(link)[0])
        if len(out) >= limit:
            break
    return out


def analyze_site(url: str, pages: int, level: str, rules: Rules) -> list[Finding]:
    from playwright.sync_api import sync_playwright  # import tardif : les tests purs n'en ont pas besoin

    pages = max(1, min(pages, 10))
    findings: list[Finding] = []

    with sync_playwright() as p:
        launch = {"headless": True, "args": ["--no-sandbox"]}
        chrome = _find_chrome()
        if chrome:
            launch["executable_path"] = chrome
        browser = p.chromium.launch(**launch)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            queue = [url]
            visited: set[str] = set()
            while queue and len(visited) < pages:
                target = queue.pop(0)
                if target in visited:
                    continue
                visited.add(target)
                try:
                    page.goto(target, wait_until="load", timeout=PAGE_TIMEOUT_MS)
                    data = page.evaluate(EXTRACT_JS)
                except Exception:
                    if target == url:
                        raise  # la page de départ est inaccessible : l'analyse échoue
                    continue  # une page secondaire en erreur est simplement ignorée
                label = page_label(target)
                findings += checks.contrast_findings(label, data["texts"], level, rules)
                findings += checks.font_findings(label, data["texts"], rules)
                findings += checks.hierarchy_findings(label, data["headings"])
                if len(visited) == 1:
                    queue = select_links(url, data["links"], pages - 1)
        finally:
            browser.close()

    for i, f in enumerate(findings, start=1):
        f.id = i
    return findings
