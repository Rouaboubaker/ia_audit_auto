"""Calcul du contraste WCAG (formule de luminance relative, WCAG 2.1 §1.4.3)."""
from __future__ import annotations

import math
import re

Color = tuple[float, float, float]  # composantes 0-255

_NUM = r"([\d.]+%?)"
_RGB = re.compile(
    rf"rgba?\(\s*{_NUM}[\s,]+{_NUM}[\s,]+{_NUM}(?:\s*[,/]\s*{_NUM})?\s*\)", re.I
)


def parse_color(s: str) -> tuple[float, float, float, float] | None:
    """'rgb(0, 0, 238)' / 'rgba(0,0,0,0.5)' / 'rgb(0 0 0 / 50%)' -> (r, g, b, alpha). None si illisible."""
    m = _RGB.fullmatch(s.strip())
    if not m:
        return None

    def num(t: str, scale: float = 1.0) -> float:
        return float(t[:-1]) / 100 * scale if t.endswith("%") else float(t)

    r, g, b = (num(m.group(i)) for i in (1, 2, 3))
    a = num(m.group(4)) if m.group(4) else 1.0
    if m.group(4) and m.group(4).endswith("%"):
        a = float(m.group(4)[:-1]) / 100
    return r, g, b, a


def blend(top: tuple[float, float, float, float], below: Color) -> Color:
    """Superpose une couleur semi-transparente `top` sur une couleur opaque `below`."""
    r, g, b, a = top
    return (r * a + below[0] * (1 - a), g * a + below[1] * (1 - a), b * a + below[2] * (1 - a))


def effective_background(layers: list[dict]) -> Color | None:
    """Fond réellement visible derrière un texte.

    `layers` : fond de l'élément, puis de son parent, etc. jusqu'à <html>, sous la forme
    {"color": "rgba(...)", "img": bool}. On empile les fonds translucides jusqu'au premier fond opaque ;
    sans fond opaque, le fond par défaut du navigateur est blanc.
    Renvoie None si on ne peut pas le déterminer (image ou dégradé de fond) : on préfère ne rien dire
    plutôt que signaler un faux positif.
    """
    stack = []
    for layer in layers:
        if layer.get("img"):
            return None
        c = parse_color(layer["color"])
        if c is None:
            return None
        if c[3] <= 0:
            continue
        stack.append(c)
        if c[3] >= 1:
            break
    result: Color = (255.0, 255.0, 255.0)
    for c in reversed(stack):
        result = blend(c, result)
    return result


def _lin(v: float) -> float:
    v /= 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def luminance(c: Color) -> float:
    return 0.2126 * _lin(c[0]) + 0.7152 * _lin(c[1]) + 0.0722 * _lin(c[2])


def ratio(c1: Color, c2: Color) -> float:
    l1, l2 = luminance(c1), luminance(c2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def floor2(x: float) -> float:
    """Arrondi vers le bas à 2 décimales : un 4,496 ne doit pas s'afficher « 4,50 » tout en échouant."""
    return math.floor(x * 100) / 100


def to_hex(c: Color) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in c)


def suggest_foreground(fg: Color, bg: Color, required: float) -> str | None:
    """Couleur de texte la plus proche de `fg` (en l'éclaircissant ou l'assombrissant) qui atteint `required`."""
    best: tuple[float, Color] | None = None
    for target in ((0.0, 0.0, 0.0), (255.0, 255.0, 255.0)):
        lo, hi = 0.0, 1.0
        mix = lambda t: tuple(fg[i] + (target[i] - fg[i]) * t for i in range(3))  # noqa: E731
        if ratio(mix(1.0), bg) < required:
            continue
        for _ in range(30):
            mid = (lo + hi) / 2
            if ratio(mix(mid), bg) >= required:
                hi = mid
            else:
                lo = mid
        # L'arrondi en hexadécimal peut faire retomber juste sous le seuil : on avance jusqu'à ce que
        # la couleur *arrondie* respecte bien le seuil.
        t = hi
        while t < 1.0:
            c = tuple(float(round(v)) for v in mix(t))
            if ratio(c, bg) >= required:
                break
            t = min(1.0, t + 0.002)
        if best is None or t < best[0]:
            best = (t, mix(t))
    return to_hex(best[1]) if best else None
