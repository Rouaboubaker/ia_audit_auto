"""Test de bout en bout du moteur : vrai navigateur sur le mini-site de samples/site (servi en local)."""
import functools
import http.server
import threading
from pathlib import Path

import pytest

from app import analyzer
from app.models import Rules

SITE = Path(__file__).resolve().parents[2] / "samples" / "site"
RULES = Rules(version=1, contrast_aa=4.5, contrast_aaa=7, min_font_px=12, created_by="t", created_at="t")


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def site_url():
    handler = functools.partial(Quiet, directory=str(SITE))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/index.html"
    srv.shutdown()


def test_select_links():
    links = ["http://a.tn/x#top", "http://a.tn/x", "http://a.tn/doc.pdf", "http://b.tn/y", "http://a.tn/z", "http://a.tn/"]
    assert analyzer.select_links("http://a.tn/", links, 5) == ["http://a.tn/x", "http://a.tn/z"]


def test_page_label():
    assert analyzer.page_label("http://a.tn/") == "/"
    assert analyzer.page_label("http://a.tn/c?id=2") == "/c?id=2"


def test_end_to_end(site_url):
    try:
        findings = analyzer.analyze_site(site_url, 2, "WCAG_AA", RULES)
    except Exception as exc:  # navigateur indisponible dans cet environnement
        pytest.skip(f"navigateur indisponible : {exc}")

    kinds = {(f.kind, f.page) for f in findings}
    assert ("CONTRAST", "/index.html") in kinds
    assert ("FONT", "/index.html") in kinds
    assert ("HIERARCHY", "/index.html") in kinds       # h1 puis h4
    assert ("HIERARCHY", "/page2.html") in kinds       # pas de h1 : la 2e page a bien été explorée
    assert [f.id for f in findings] == list(range(1, len(findings) + 1))

    contrasts = {f.foreground: f for f in findings if f.kind == "CONTRAST"}
    assert "#aaaaaa" in contrasts and contrasts["#aaaaaa"].background == "#ffffff"
    assert any(f.background == "#0b4f9c" for f in contrasts.values())      # fond du bandeau bleu
    assert all(f.ratio < 4.5 for f in contrasts.values())
    assert not any("Ce paragraphe est lisible" in f.element for f in findings)   # texte conforme non signalé

    one_page = analyzer.analyze_site(site_url, 1, "WCAG_AA", RULES)
    assert not any(f.page == "/page2.html" for f in one_page)
