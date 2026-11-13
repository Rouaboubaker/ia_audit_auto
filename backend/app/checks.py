"""Règles d'analyse d'une page : fonctions pures (pas de navigateur), faciles à tester.

Entrée : les données extraites par analyzer.py (textes avec styles calculés, titres h1-h6).
Sortie : des constats `Finding` (sans id : il est attribué à la fin par l'analyseur).
"""
from __future__ import annotations

from . import contrast as C
from . import recommendations as R
from .models import Finding, Rules

MAX_CONTRAST_PER_PAGE = 25


def _required(level: str, large: bool, rules: Rules) -> float:
    """Seuil de contraste. Le texte « large » (≥ 24 px, ou ≥ 18,66 px en gras) a un seuil réduit (WCAG)."""
    if level == "WCAG_AAA":
        base, cap = rules.contrast_aaa, 4.5
    else:
        base, cap = rules.contrast_aa, 3.0
    return min(base, cap) if large else base


def _describe(sel: str, text: str) -> str:
    return f"{sel} « {text} »"


def contrast_findings(page: str, texts: list[dict], level: str, rules: Rules) -> list[Finding]:
    groups: dict[tuple, dict] = {}
    for t in texts:
        fg = C.parse_color(t["color"])
        bg = C.effective_background(t["layers"])
        if fg is None or bg is None:
            continue  # fond indéterminable : on ne signale pas
        fg_rgb = C.blend(fg, bg) if fg[3] < 1 else fg[:3]
        large = t["size"] >= 24 or (t["size"] >= 18.66 and t["weight"] >= 700)
        required = _required(level, large, rules)
        r = C.ratio(fg_rgb, bg)
        if r >= required:
            continue
        key = (C.to_hex(fg_rgb), C.to_hex(bg), large)
        g = groups.setdefault(key, {"first": t, "count": 0, "ratio": r, "required": required,
                                    "fg": fg_rgb, "bg": bg})
        g["count"] += 1

    out = []
    for (fg_hex, bg_hex, _), g in sorted(groups.items(), key=lambda kv: kv[1]["ratio"])[:MAX_CONTRAST_PER_PAGE]:
        suggestion = C.suggest_foreground(g["fg"], g["bg"], g["required"])
        element = _describe(g["first"]["sel"], g["first"]["text"])
        if g["count"] > 1:
            element += f" (+{g['count'] - 1} similaires)"
        out.append(Finding(
            id=0, page=page, kind="CONTRAST", element=element,
            foreground=fg_hex, background=bg_hex, ratio=C.floor2(g["ratio"]), compliant=False,
            recommendation=R.contrast(g["ratio"], g["required"], level, g["count"], suggestion),
        ))
    return out


def font_findings(page: str, texts: list[dict], rules: Rules) -> list[Finding]:
    by_size: dict[float, dict] = {}
    for t in texts:
        if t["size"] < rules.min_font_px:
            g = by_size.setdefault(t["size"], {"first": t, "count": 0})
            g["count"] += 1
    out = []
    for size, g in sorted(by_size.items()):
        element = _describe(g["first"]["sel"], g["first"]["text"])
        if g["count"] > 1:
            element += f" (+{g['count'] - 1} similaires)"
        out.append(Finding(
            id=0, page=page, kind="FONT", element=element, compliant=False,
            recommendation=R.font(size, rules.min_font_px, g["count"]),
        ))
    return out


def hierarchy_findings(page: str, headings: list[dict]) -> list[Finding]:
    out = []
    if not headings:
        return [Finding(id=0, page=page, kind="HIERARCHY", element="body", compliant=False,
                        recommendation=R.hierarchy("La page ne contient aucun titre (h1 à h6)"))]
    if not any(h["level"] == 1 for h in headings):
        out.append(Finding(id=0, page=page, kind="HIERARCHY", element="body", compliant=False,
                           recommendation=R.hierarchy("La page n'a pas de titre de niveau 1 (h1)")))
    prev = 0
    for h in headings:
        if prev and h["level"] > prev + 1:
            out.append(Finding(
                id=0, page=page, kind="HIERARCHY",
                element=_describe(f"h{h['level']}", h["text"]), compliant=False,
                recommendation=R.hierarchy(f"Saut de niveau de titre : h{prev} suivi de h{h['level']}")))
        prev = h["level"]
    return out
