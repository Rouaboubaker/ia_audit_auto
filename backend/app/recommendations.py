"""Textes de recommandation, ancrés sur le référentiel WCAG via le RAG (rag.py).

Aujourd'hui : on retrouve la fiche du critère concerné et on y ajoute les chiffres mesurés.
Évolution prévue : confier la rédaction à un LLM en lui donnant cette fiche comme contexte.
"""
from __future__ import annotations

from . import rag

LEVEL_LABEL = {"WCAG_AA": "WCAG AA", "WCAG_AAA": "WCAG AAA"}


def _fix(wcag_id: str) -> tuple[str, str]:
    found = rag.retrieve({"wcag": [wcag_id], "help": ""})
    if not found:
        return wcag_id, ""
    c = found[0]
    return f'{c["id"]} « {c["name"]} »', c["fix"]


def contrast(ratio: float, required: float, level: str, count: int, suggestion: str | None) -> str:
    crit, fix = _fix("1.4.6" if level == "WCAG_AAA" else "1.4.3")
    txt = (f"Contraste de {ratio:.2f}:1 pour un minimum de {required:g}:1 "
           f"({LEVEL_LABEL[level]}, critère {crit}). ")
    if suggestion:
        txt += f"Couleur de texte suggérée : {suggestion}. "
    if count > 1:
        txt += f"Même couleur utilisée sur {count} éléments. "
    return txt + fix


def font(size: float, minimum: float, count: int) -> str:
    crit, fix = _fix("1.4.4")
    txt = f"Texte de {size:g} px, inférieur au minimum de {minimum:g} px (critère {crit}). "
    if count > 1:
        txt += f"{count} éléments concernés. "
    return txt + fix


def hierarchy(problem: str) -> str:
    crit, fix = _fix("1.3.1")
    return f"{problem} (critères {crit} et 2.4.6). {fix}"
