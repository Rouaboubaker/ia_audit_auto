import os
import json
import shutil
from datetime import datetime
from typing import Tuple, List, Dict, Any
from playwright.sync_api import sync_playwright

BASE_DIR = os.path.dirname(os.path.abspath(__file__))          # backend/app
DATA_CORPUS_DIR = os.path.join(BASE_DIR, "data", "corpus")     # backend/app/data/corpus
SAMPLES_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "samples"))


def capture_portal_page(
    url: str,
    portal_name: str,
    page_slug: str = "accueil",
    save_to_samples: bool = True
) -> Tuple[str, str]:
    """Action A1 (Dev 1) : Capture 1920x1080 + extraction DOM/CSS."""
    images_dir = os.path.join(DATA_CORPUS_DIR, "images", portal_name)
    meta_dir = os.path.join(DATA_CORPUS_DIR, "metadata", portal_name)
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(meta_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename_base = f"{portal_name}_{page_slug}_{timestamp}"
    screenshot_path = os.path.join(images_dir, f"{filename_base}.png")
    metadata_path = os.path.join(meta_dir, f"{filename_base}.json")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
            locale="fr-TN",
            ignore_https_errors=True
        )
        page = context.new_page()

        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        page.screenshot(path=screenshot_path, full_page=False)

        dom_elements = page.evaluate("""() => {
            const selectors = 'h1, h2, h3, h4, h5, h6, p, a, button, span, label, input';
            const elements = [];
            document.querySelectorAll(selectors).forEach(el => {
                const text = (el.innerText || el.value || '').trim();
                const rect = el.getBoundingClientRect();
                if (text.length > 0 && rect.width > 0 && rect.height > 0 && rect.top < 1080) {
                    const style = window.getComputedStyle(el);
                    elements.push({
                        tag: el.tagName.toLowerCase(),
                        text: text.substring(0, 150),
                        coordinates: {
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            w: Math.round(rect.width),
                            h: Math.round(rect.height)
                        },
                        css: {
                            fontSize: style.fontSize,
                            fontFamily: style.fontFamily,
                            fontWeight: style.fontWeight,
                            color: style.color,
                            backgroundColor: style.backgroundColor
                        }
                    });
                }
            });
            return elements;
        }""")

        browser.close()

    metadata_payload = {
        "project": "CAD-eAccess-A1",
        "action": "A1 - Capture & Corpus",
        "portal": portal_name,
        "page_slug": page_slug,
        "url": url,
        "viewport": {"width": 1920, "height": 1080},
        "timestamp": timestamp,
        "screenshot_path": screenshot_path,
        "dom_elements_count": len(dom_elements),
        "dom_elements": dom_elements
    }

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata_payload, f, indent=4, ensure_ascii=False)

    if save_to_samples and os.path.isdir(SAMPLES_DIR):
        shutil.copy2(screenshot_path, os.path.join(SAMPLES_DIR, f"{portal_name}_{page_slug}.png"))

    return screenshot_path, metadata_path


def build_coco_annotation_structure(captured_items: List[Dict[str, Any]]) -> str:
    """
    Génère le fichier annotations_coco.json (Livrable D1.1) avec les catégories
    d'anomalies WCAG 2.1 prêtes pour la vérité terrain.
    """
    annotations_dir = os.path.join(DATA_CORPUS_DIR, "annotations")
    os.makedirs(annotations_dir, exist_ok=True)
    coco_path = os.path.join(annotations_dir, "annotations_coco.json")

    coco_dataset = {
        "info": {
            "description": "Corpus Pilote CAD-eAccess-A1 (IA-Audit-Auto) - Portails UGE",
            "version": "1.0",
            "year": 2026
        },
        "categories": [
            {"id": 1, "name": "contrast_fail_aa", "supercategory": "wcag_contrast"},
            {"id": 2, "name": "contrast_warning_aaa", "supercategory": "wcag_contrast"},
            {"id": 3, "name": "typography_small_text", "supercategory": "wcag_typography"},
            {"id": 4, "name": "heading_hierarchy_error", "supercategory": "wcag_structure"}
        ],
        "images": [],
        "annotations": []
    }

    image_id = 1
    for item in captured_items:
        if item["status"] == "SUCCESS":
            coco_dataset["images"].append({
                "id": image_id,
                "file_name": os.path.relpath(item["image"], DATA_CORPUS_DIR).replace("\\", "/"),
                "width": 1920,
                "height": 1080,
                "portal": item["portal"],
                "page_slug": item["page_slug"],
                "url": item["url"]
            })
            image_id += 1

    with open(coco_path, "w", encoding="utf-8") as f:
        json.dump(coco_dataset, f, indent=4, ensure_ascii=False)

    return coco_path


def run_pilot_corpus_capture(portals: List[Dict[str, str]]) -> Dict[str, Any]:
    report = []
    for portal in portals:
        try:
            img_path, meta_path = capture_portal_page(
                url=portal["url"],
                portal_name=portal["name"],
                page_slug=portal.get("slug", "accueil")
            )
            report.append({
                "portal": portal["name"],
                "page_slug": portal.get("slug", "accueil"),
                "url": portal["url"],
                "status": "SUCCESS",
                "image": img_path,
                "metadata": meta_path
            })
        except Exception as e:
            report.append({
                "portal": portal["name"],
                "page_slug": portal.get("slug", "accueil"),
                "url": portal["url"],
                "status": "FAILED",
                "error": str(e)
            })

    coco_file = build_coco_annotation_structure(report)
    return {"captures": report, "coco_annotations_file": coco_file}


if __name__ == "__main__":
    # 2 portails pilotes : page d'accueil + sous-pages clés
    portails_pilotes = [
        # Portail 1 : Tunisie.gov.tn
        {"name": "tunisie_gov", "slug": "accueil", "url": "https://www.tunisie.gov.tn"},
        {"name": "tunisie_gov", "slug": "annuaire", "url": "https://www.tunisie.gov.tn/fr/annuaire"},
        {"name": "tunisie_gov", "slug": "services", "url": "https://www.tunisie.gov.tn/fr/services-en-ligne"},
        # Portail 2 : CNSS.tn
        {"name": "cnss", "slug": "accueil", "url": "https://www.cnss.tn"},
        {"name": "cnss", "slug": "assures", "url": "https://www.cnss.tn/fr/web/assures/accueil"},
        {"name": "cnss", "slug": "employeurs", "url": "https://www.cnss.tn/fr/web/employeurs/accueil"}
    ]
    results = run_pilot_corpus_capture(portails_pilotes)
    print(json.dumps(results, indent=4, ensure_ascii=False))