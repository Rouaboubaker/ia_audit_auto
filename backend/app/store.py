"""Stockage EN MÉMOIRE (démo) : tout est perdu à l'arrêt du serveur.
Prochaine étape : remplacer par une base (SQLite/PostgreSQL) en gardant la même interface."""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from .models import Dossier, F1Point, Rules, User
from .security import hash_password

DEMO_PASSWORD = "Demo2026!"

SEED_USERS = [
    ("Administrateur UGE", "admin@uge.gov.tn", "ADMIN"),
    ("Responsable Portail", "manager@portail.gov.tn", "PORTAL_MANAGER"),
    ("Instructeur UGE", "instructeur@uge.gov.tn", "INSTRUCTOR"),
    ("Auditeur WCAG", "auditeur@expert.org", "WCAG_AUDITOR"),
    ("Auditeur Junior", "junior@expert.org", "JUNIOR_AUDITOR"),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.users: dict[int, User] = {}
        self.passwords: dict[int, str] = {}
        self.tokens: dict[str, int] = {}
        self.rules: list[Rules] = []
        self.dossiers: dict[int, Dossier] = {}
        self.owners: dict[int, int] = {}          # id dossier -> id de l'utilisateur qui l'a soumis
        self.errors: dict[int, str] = {}          # id dossier -> message si l'analyse a échoué
        self.durations: list[float] = []          # durées d'analyse (secondes)
        self.f1_history: list[F1Point] = []
        self._seq = {"user": 0, "dossier": 0}
        self._seed()

    def next_id(self, kind: str) -> int:
        with self.lock:
            self._seq[kind] += 1
            return self._seq[kind]

    def _seed(self) -> None:
        pw = hash_password(DEMO_PASSWORD)
        for name, email, role in SEED_USERS:
            uid = self.next_id("user")
            self.users[uid] = User(id=uid, name=name, email=email, role=role, status="ACTIVE", invited=False)
            self.passwords[uid] = pw
        self.rules.append(Rules(version=1, contrast_aa=4.5, contrast_aaa=7, min_font_px=12,
                                created_by="Système", created_at=now_iso()))
