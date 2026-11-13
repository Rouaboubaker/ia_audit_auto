"""Tests de la logique pure : contraste, règles d'analyse, modèles (aucun navigateur requis)."""
from app import checks
from app import contrast as C
from app.models import Finding, Rules


def rules(aa=4.5, aaa=7, font=12):
    return Rules(version=1, contrast_aa=aa, contrast_aaa=aaa, min_font_px=font, created_by="t", created_at="t")


# ---- modèles : le piège des alias ----------------------------------------
def test_rules_json_keys_match_frontend():
    d = rules().model_dump(by_alias=True)
    assert {"contrastAA", "contrastAAA", "minFontPx", "createdBy", "createdAt", "version"} == set(d)


def test_finding_camel_and_optional():
    d = Finding(id=1, page="/", kind="FONT", element="p", compliant=False, recommendation="x") \
        .model_dump(by_alias=True, exclude_none=True)
    assert "ratio" not in d and "decision" not in d


# ---- contraste ------------------------------------------------------------
def test_ratio_black_white():
    assert round(C.ratio((0, 0, 0), (255, 255, 255)), 2) == 21.0


def test_ratio_known_value():
    # #767676 sur blanc : le gris le plus clair qui passe AA (4,54:1)
    assert 4.5 <= C.ratio((0x76, 0x76, 0x76), (255, 255, 255)) < 4.6


def test_parse_color_variants():
    assert C.parse_color("rgb(0, 0, 238)") == (0, 0, 238, 1.0)
    assert C.parse_color("rgba(0, 0, 0, 0.5)") == (0, 0, 0, 0.5)
    assert C.parse_color("rgb(0 0 0 / 50%)")[3] == 0.5
    assert C.parse_color("color(srgb 1 0 0)") is None


def test_effective_background_default_is_white():
    assert C.effective_background([{"color": "rgba(0, 0, 0, 0)", "img": False}]) == (255, 255, 255)


def test_effective_background_takes_first_opaque_ancestor():
    layers = [{"color": "rgba(0, 0, 0, 0)", "img": False}, {"color": "rgb(11, 79, 156)", "img": False},
              {"color": "rgb(0, 0, 0)", "img": False}]
    assert C.effective_background(layers) == (11, 79, 156)


def test_effective_background_unknown_with_image():
    assert C.effective_background([{"color": "rgba(0, 0, 0, 0)", "img": True}]) is None


def test_translucent_background_is_blended():
    bg = C.effective_background([{"color": "rgba(0, 0, 0, 0.5)", "img": False}])
    assert bg == (127.5, 127.5, 127.5)


def test_floor2_never_rounds_up_a_failure():
    assert C.floor2(4.4999) == 4.49


def test_suggestion_reaches_threshold():
    fg, bg = (0xAA, 0xAA, 0xAA), (255.0, 255.0, 255.0)
    s = C.suggest_foreground(fg, bg, 4.5)
    r, g, b = int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16)
    assert C.ratio((r, g, b), bg) >= 4.5


# ---- règles d'analyse -----------------------------------------------------
def text(color, bg="rgba(0, 0, 0, 0)", size=16, weight=400, sel="p", t="Texte"):
    return {"sel": sel, "text": t, "color": color, "size": size, "weight": weight,
            "layers": [{"color": bg, "img": False}]}


def test_contrast_flags_only_failures_and_groups():
    texts = [text("rgb(170, 170, 170)"), text("rgb(170, 170, 170)"), text("rgb(0, 0, 0)")]
    out = checks.contrast_findings("/", texts, "WCAG_AA", rules())
    assert len(out) == 1
    f = out[0]
    assert f.kind == "CONTRAST" and f.foreground == "#aaaaaa" and f.background == "#ffffff"
    assert f.ratio < 4.5 and not f.compliant and "(+1 similaires)" in f.element
    assert "suggérée" in f.recommendation


def test_aaa_is_stricter_than_aa():
    gris = [text("rgb(100, 100, 100)")]   # ~5,9:1 : passe AA, échoue AAA
    assert checks.contrast_findings("/", gris, "WCAG_AA", rules()) == []
    assert len(checks.contrast_findings("/", gris, "WCAG_AAA", rules())) == 1


def test_large_text_has_lower_threshold():
    t = [text("rgb(140, 140, 140)", size=32)]    # ~3,4:1
    assert checks.contrast_findings("/", t, "WCAG_AA", rules()) == []
    assert len(checks.contrast_findings("/", [text("rgb(140, 140, 140)", size=16)], "WCAG_AA", rules())) == 1


def test_contrast_uses_rules_version_thresholds():
    t = [text("rgb(100, 100, 100)")]   # ~5,9:1
    assert checks.contrast_findings("/", t, "WCAG_AA", rules(aa=4.5)) == []
    assert len(checks.contrast_findings("/", t, "WCAG_AA", rules(aa=6.0))) == 1


def test_unknown_background_is_skipped():
    t = text("rgb(255, 255, 255)")
    t["layers"] = [{"color": "rgba(0, 0, 0, 0)", "img": True}]
    assert checks.contrast_findings("/", [t], "WCAG_AA", rules()) == []


def test_font_findings():
    out = checks.font_findings("/", [text("x", size=9), text("x", size=9), text("x", size=16)], rules())
    assert len(out) == 1 and out[0].kind == "FONT" and out[0].ratio is None
    assert "9 px" in out[0].recommendation and "12 px" in out[0].recommendation


def test_hierarchy_findings():
    hs = [{"level": 2, "text": "A"}, {"level": 4, "text": "B"}]
    out = checks.hierarchy_findings("/p", hs)
    assert len(out) == 2   # pas de h1 + saut h2 -> h4
    assert all(f.kind == "HIERARCHY" and f.foreground is None and not f.compliant for f in out)
    assert checks.hierarchy_findings("/", [{"level": 1, "text": "T"}, {"level": 2, "text": "S"}]) == []
    assert len(checks.hierarchy_findings("/", [])) == 1
