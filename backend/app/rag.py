"""Étape 4 – RAG : retrouve le critère WCAG 2.1 qui correspond à chaque violation.

MVP : base de ~25 critères (data/wcag_criteria.json) indexée en TF-IDF (scikit-learn).
Pour la version finale : remplacer `_build_index` / `search` par Chroma ou FAISS + embeddings,
et ajouter les guides UGE comme documents supplémentaires dans le même JSON.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DATA = Path(__file__).parent / "data" / "wcag_criteria.json"


@lru_cache(maxsize=1)
def _load():
    docs = json.loads(DATA.read_text(encoding="utf-8"))
    corpus = [f'{d["id"]} {d["name"]} {d["description"]} {d["fix"]}' for d in docs]
    vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
    matrix = vec.fit_transform(corpus)
    return docs, vec, matrix


def get_criterion(wcag_id: str) -> dict | None:
    docs, _, _ = _load()
    return next((d for d in docs if d["id"] == wcag_id), None)


def search(query: str, k: int = 2) -> list[dict]:
    docs, vec, matrix = _load()
    scores = cosine_similarity(vec.transform([query]), matrix)[0]
    best = scores.argsort()[::-1][:k]
    return [{**docs[i], "score": float(scores[i])} for i in best if scores[i] > 0]


def retrieve(violation: dict, k: int = 2) -> list[dict]:
    """Critères pertinents pour une violation.
    1) correspondance exacte via les numéros WCAG donnés par le moteur ;
    2) sinon recherche sémantique sur l'intitulé de la règle."""
    found = []
    for wid in violation.get("wcag", []):
        c = get_criterion(wid)
        if c:
            found.append({**c, "score": 1.0})
    if found:
        return found[:k]
    return search(violation.get("help", "") + " " + violation.get("id", ""), k)
