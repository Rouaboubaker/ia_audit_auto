"""Logique métier de l'API (sans FastAPI : on la teste directement). Les routes de main.py sont de fines enveloppes."""
from __future__ import annotations

import hmac
import logging
import os
import re
import secrets
import time

from .analyzer import analyze_site
from .errors import ApiException
from .models import (Decision, Dossier, Divergences, DivergenceCase, F1Point, InvitationRequest, Kpi,
                     LabelDecision, LoginRequest, LoginResponse, PublishRulesRequest, RegisterRequest,
                     Rules, SubmitDossierRequest, User)
from .security import check_public_url, hash_password, verify_password
from .store import Store, now_iso

log = logging.getLogger("audit")

MFA_ROLES = {"ADMIN", "INSTRUCTOR", "WCAG_AUDITOR"}
MIN_STANDARD = {"contrast_aa": 4.5, "contrast_aaa": 7.0, "min_font_px": 12.0}
MAX_PAGES = 10
# Objectifs d'affichage des KPI : valeurs de démonstration, à confirmer avec l'encadrant.
F1_TARGET, PORTALS_TARGET, MAX_REPORT_MINUTES, PUBLICATIONS_TARGET = 0.85, 50, 10.0, 4
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _not_found() -> ApiException:
    return ApiException(404, "NOT_FOUND", "Ressource introuvable.")


class Service:
    def __init__(self, store: Store | None = None, analyze=analyze_site):
        self.s = store or Store()
        self._analyze = analyze
        # Code à deux facteurs de DÉMO (fixe). En production : TOTP (application d'authentification).
        self.mfa_code = os.environ.get("MFA_CODE", "123456")

    # ---------------------------------------------------------------- comptes
    def login(self, req: LoginRequest) -> LoginResponse:
        with self.s.lock:
            user = next((u for u in self.s.users.values() if u.email.lower() == req.email.strip().lower()), None)
            if not user or not verify_password(req.password, self.s.passwords.get(user.id)):
                raise ApiException(401, "INVALID_CREDENTIALS", "Courriel ou mot de passe incorrect.")
            if user.status == "PENDING":
                raise ApiException(403, "ACCOUNT_PENDING", "Votre compte est en attente de validation.")
            if user.status == "DISABLED":
                raise ApiException(403, "ACCOUNT_DISABLED", "Votre compte est désactivé.")
            if user.role in MFA_ROLES:
                if not req.code:
                    raise ApiException(403, "MFA_REQUIRED", "Un code de vérification est requis.")
                if not hmac.compare_digest(req.code.strip(), self.mfa_code):
                    raise ApiException(401, "INVALID_CODE", "Code de vérification incorrect.")
            token = secrets.token_urlsafe(32)
            self.s.tokens[token] = user.id
            return LoginResponse(token=token, user=user.model_copy())

    def register(self, req: RegisterRequest) -> User:
        if not req.name.strip() or not EMAIL_RE.match(req.email.strip()) or len(req.password) < 8:
            raise ApiException(400, "VALIDATION_ERROR",
                               "Nom, courriel valide et mot de passe d'au moins 8 caractères requis.")
        with self.s.lock:
            if any(u.email.lower() == req.email.strip().lower() for u in self.s.users.values()):
                raise ApiException(409, "EMAIL_EXISTS", "Ce courriel est déjà utilisé.")
            uid = self.s.next_id("user")
            user = User(id=uid, name=req.name.strip(), email=req.email.strip(), role="PORTAL_MANAGER",
                        status="PENDING", invited=False)
            self.s.users[uid] = user
            self.s.passwords[uid] = hash_password(req.password)
            return user.model_copy()

    def authenticate(self, token: str) -> User:
        with self.s.lock:
            uid = self.s.tokens.get(token)
            user = self.s.users.get(uid) if uid else None
            if not user or user.status != "ACTIVE":
                raise ApiException(401, "UNAUTHORIZED", "Session expirée ou invalide.")
            return user.model_copy()

    # --------------------------------------------------------------- dossiers
    def _get(self, user: User, dossier_id: int) -> Dossier:
        d = self.s.dossiers.get(dossier_id)
        if not d or (user.role == "PORTAL_MANAGER" and self.s.owners[dossier_id] != user.id):
            raise _not_found()
        return d

    def list_dossiers(self, user: User) -> list[Dossier]:
        with self.s.lock:
            items = [d for d in self.s.dossiers.values()
                     if user.role != "PORTAL_MANAGER" or self.s.owners[d.id] == user.id]
            return [d.model_copy(deep=True) for d in sorted(items, key=lambda d: -d.id)]

    def get_dossier(self, user: User, dossier_id: int) -> Dossier:
        with self.s.lock:
            return self._get(user, dossier_id).model_copy(deep=True)

    def submit(self, user: User, req: SubmitDossierRequest) -> Dossier:
        check_public_url(req.url)
        if not 1 <= req.pages <= MAX_PAGES:
            raise ApiException(400, "VALIDATION_ERROR", f"Le nombre de pages doit être compris entre 1 et {MAX_PAGES}.")
        with self.s.lock:
            did = self.s.next_id("dossier")
            d = Dossier(id=did, url=req.url, pages=req.pages, requested_level=req.requested_level,
                        status="ANALYZING", rules_version=self.s.rules[-1].version,
                        submitted_by=user.name, created_at=now_iso())
            self.s.dossiers[did] = d
            self.s.owners[did] = user.id
            return d.model_copy(deep=True)

    def run_analysis(self, dossier_id: int) -> None:
        """Exécutée en arrière-plan après la soumission. Un dossier garde la version de règles de sa soumission."""
        with self.s.lock:
            d = self.s.dossiers[dossier_id]
            url, pages, level = d.url, d.pages, d.requested_level
            rules = next(r for r in self.s.rules if r.version == d.rules_version)
        t0 = time.time()
        try:
            findings, error = self._analyze(url, pages, level, rules), None
        except Exception as exc:  # noqa: BLE001
            log.exception("Analyse échouée pour le dossier %s", dossier_id)
            findings, error = [], f"{type(exc).__name__}: {exc}"
        with self.s.lock:
            d.findings = findings
            if error:
                # Le contrat n'a pas d'état « échec ». On ne passe PAS en REVIEWED : un dossier jamais analysé
                # ne doit pas pouvoir recevoir de label. Il reste ANALYZED, sans constat, avec l'erreur en journal.
                self.s.errors[dossier_id] = error
                d.status = "ANALYZED"
            else:
                d.status = "ANALYZED" if findings else "REVIEWED"  # aucun constat : rien à relire
                self.s.durations.append(time.time() - t0)

    def decide_finding(self, user: User, dossier_id: int, finding_id: int, decision: Decision) -> Dossier:
        with self.s.lock:
            d = self._get(user, dossier_id)
            if d.status == "ANALYZING":
                raise ApiException(409, "ANALYSIS_PENDING", "L'analyse n'est pas terminée.")
            if d.status == "DECIDED":
                raise ApiException(409, "ALREADY_DECIDED", "Une décision de label a déjà été prise.")
            f = next((f for f in d.findings if f.id == finding_id), None)
            if not f:
                raise _not_found()
            f.decision = decision
            d.status = "REVIEWED" if all(x.decision for x in d.findings) else "ANALYZED"
            return d.model_copy(deep=True)

    def set_label(self, user: User, dossier_id: int, label: LabelDecision) -> Dossier:
        with self.s.lock:
            d = self._get(user, dossier_id)
            if d.status == "DECIDED":
                raise ApiException(409, "ALREADY_DECIDED", "Une décision de label a déjà été prise.")
            if d.status != "REVIEWED":
                raise ApiException(409, "REVIEW_INCOMPLETE", "Tous les constats doivent être revus avant la décision.")
            d.label, d.status = label, "DECIDED"
            return d.model_copy(deep=True)

    # ----------------------------------------------------------------- règles
    def current_rules(self) -> Rules:
        with self.s.lock:
            return self.s.rules[-1].model_copy()

    def list_rules(self) -> list[Rules]:
        with self.s.lock:
            return [r.model_copy() for r in reversed(self.s.rules)]

    def publish_rules(self, user: User, req: PublishRulesRequest) -> Rules:
        for field, minimum in MIN_STANDARD.items():
            if getattr(req, field) < minimum:
                raise ApiException(400, "RULE_BELOW_STANDARD",
                                   "Les seuils proposés sont inférieurs à la norme "
                                   "(contraste AA ≥ 4,5 ; AAA ≥ 7 ; police ≥ 12 px).")
        with self.s.lock:
            r = Rules(version=self.s.rules[-1].version + 1, contrast_aa=req.contrast_aa,
                      contrast_aaa=req.contrast_aaa, min_font_px=req.min_font_px,
                      created_by=user.name, created_at=now_iso())
            self.s.rules.append(r)
            return r.model_copy()

    # ----------------------------------------------------------- utilisateurs
    def list_users(self) -> list[User]:
        with self.s.lock:
            return [u.model_copy() for u in self.s.users.values()]

    def invite(self, req: InvitationRequest) -> User:
        if not req.name.strip() or not EMAIL_RE.match(req.email.strip()):
            raise ApiException(400, "VALIDATION_ERROR", "Nom et courriel valide requis.")
        with self.s.lock:
            if any(u.email.lower() == req.email.strip().lower() for u in self.s.users.values()):
                raise ApiException(409, "EMAIL_EXISTS", "Ce courriel est déjà utilisé.")
            uid = self.s.next_id("user")
            u = User(id=uid, name=req.name.strip(), email=req.email.strip(), role=req.role,
                     status="PENDING", invited=True)
            self.s.users[uid] = u
            return u.model_copy()

    def set_user_status(self, user_id: int, status: str) -> User:
        with self.s.lock:
            u = self.s.users.get(user_id)
            if not u:
                raise _not_found()
            u.status = status
            if status == "DISABLED":  # coupe les sessions ouvertes
                self.s.tokens = {t: uid for t, uid in self.s.tokens.items() if uid != user_id}
            return u.model_copy()

    # ------------------------------------------------------------- statistiques
    def _decided_findings(self):
        return [f for d in self.s.dossiers.values() for f in d.findings if f.decision]

    def divergences(self) -> Divergences:
        """Faux positifs = constats écartés (DISMISSED) par un instructeur. Les faux négatifs
        (constats ajoutés à la main, US15) ne sont pas encore gérés : liste vide."""
        with self.s.lock:
            fp = [DivergenceCase(page=f.page, element=f.element, ratio=f.ratio,
                                 reason="Constat écarté par l'instructeur")
                  for f in self._decided_findings() if f.decision == "DISMISSED"]
        return Divergences(false_positives=fp, false_negatives=[])

    def kpi(self) -> Kpi:
        with self.s.lock:
            analysed = sum(1 for d in self.s.dossiers.values() if d.status != "ANALYZING")
            avg = sum(self.s.durations) / len(self.s.durations) / 60 if self.s.durations else 0.0
            return Kpi(f1_history=[p.model_copy() for p in self.s.f1_history], f1_target=F1_TARGET,
                       portals_analysed=analysed, portals_target=PORTALS_TARGET,
                       avg_report_minutes=round(avg, 2), max_report_minutes=MAX_REPORT_MINUTES,
                       publications=len(self.s.rules), publications_target=PUBLICATIONS_TARGET)

    def retrain(self) -> Kpi:
        """Calcule un point F1 réel à partir des décisions des instructeurs : TP = constats confirmés,
        FP = constats écartés, FN = 0 (les ajouts manuels ne sont pas encore gérés). Ne réentraîne aucun modèle."""
        with self.s.lock:
            decided = self._decided_findings()
            tp = sum(1 for f in decided if f.decision == "CONFIRMED")
            fp = sum(1 for f in decided if f.decision == "DISMISSED")
            if tp + fp == 0:
                raise ApiException(409, "NO_FEEDBACK", "Aucune décision d'instructeur disponible.")
            f1 = 2 * tp / (2 * tp + fp)
            self.s.f1_history.append(F1Point(month=len(self.s.f1_history) + 1, value=round(f1, 3)))
        return self.kpi()
