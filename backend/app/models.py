"""Modèles du contrat d'API (miroir de src/app/core/models.ts côté Angular).

Python écrit en snake_case, le JSON est en camelCase : `alias_generator=to_camel` fait la conversion.
Piège : to_camel("contrast_aa") donne "contrastAa", alors que le frontend attend "contrastAA".
On impose donc l'alias exact sur ces deux champs avec Field(alias=...).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---- Comptes -------------------------------------------------------------
Role = Literal["ADMIN", "PORTAL_MANAGER", "INSTRUCTOR", "WCAG_AUDITOR", "JUNIOR_AUDITOR"]
UserStatus = Literal["PENDING", "ACTIVE", "DISABLED"]


class User(CamelModel):
    id: int
    name: str
    email: str
    role: Role
    status: UserStatus
    invited: bool


class LoginRequest(CamelModel):
    email: str
    password: str
    code: str | None = None


class LoginResponse(CamelModel):
    token: str
    user: User


class RegisterRequest(CamelModel):
    name: str
    email: str
    password: str


class InvitationRequest(CamelModel):
    name: str
    email: str
    role: Role


class StatusUpdate(CamelModel):
    status: Literal["ACTIVE", "DISABLED"]


# ---- Dossiers et constats ------------------------------------------------
FindingKind = Literal["CONTRAST", "HIERARCHY", "FONT"]
Decision = Literal["CONFIRMED", "DISMISSED"]
Level = Literal["WCAG_AA", "WCAG_AAA"]
LabelDecision = Literal["WCAG_AA", "WCAG_AAA", "REJECTED"]
DossierStatus = Literal["ANALYZING", "ANALYZED", "REVIEWED", "DECIDED"]


class Finding(CamelModel):
    id: int
    page: str
    kind: FindingKind
    element: str
    foreground: str | None = None
    background: str | None = None
    ratio: float | None = None
    compliant: bool
    recommendation: str
    decision: Decision | None = None


class Dossier(CamelModel):
    id: int
    url: str
    pages: int
    requested_level: Level
    status: DossierStatus
    label: LabelDecision | None = None
    rules_version: int
    submitted_by: str
    created_at: str
    findings: list[Finding] = Field(default_factory=list)


class SubmitDossierRequest(CamelModel):
    url: str
    pages: int
    requested_level: Level


class DecisionUpdate(CamelModel):
    decision: Decision


class LabelUpdate(CamelModel):
    label: LabelDecision


# ---- Règles --------------------------------------------------------------
class Rules(CamelModel):
    version: int
    contrast_aa: float = Field(alias="contrastAA")
    contrast_aaa: float = Field(alias="contrastAAA")
    min_font_px: float
    created_by: str
    created_at: str


class PublishRulesRequest(CamelModel):
    contrast_aa: float = Field(alias="contrastAA")
    contrast_aaa: float = Field(alias="contrastAAA")
    min_font_px: float


# ---- Analyses ------------------------------------------------------------
class DivergenceCase(CamelModel):
    page: str
    element: str
    ratio: float | None = None
    reason: str


class Divergences(CamelModel):
    false_positives: list[DivergenceCase]
    false_negatives: list[DivergenceCase]


class F1Point(CamelModel):
    month: int
    value: float


class Kpi(CamelModel):
    f1_history: list[F1Point]
    f1_target: float
    portals_analysed: int
    portals_target: int
    avg_report_minutes: float
    max_report_minutes: float
    publications: int
    publications_target: int
