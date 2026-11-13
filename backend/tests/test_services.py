"""Tests du contrat d'API au niveau métier (services), avec un faux analyseur : rapides, sans réseau."""
import pytest

from app.errors import ApiException
from app.models import (Finding, InvitationRequest, LoginRequest, PublishRulesRequest, RegisterRequest,
                        SubmitDossierRequest)
from app.services import Service
from app.store import DEMO_PASSWORD, Store


def fake_analyzer(url, pages, level, rules):
    return [Finding(id=1, page="/", kind="CONTRAST", element="p", foreground="#aaaaaa", background="#ffffff",
                    ratio=2.3, compliant=False, recommendation="r"),
            Finding(id=2, page="/", kind="FONT", element="small", compliant=False, recommendation="r")]


@pytest.fixture
def svc(monkeypatch):
    monkeypatch.setenv("ALLOW_PRIVATE", "1")
    return Service(Store(), analyze=fake_analyzer)


def login(svc, email, code=None, password=DEMO_PASSWORD):
    return svc.login(LoginRequest(email=email, password=password, code=code)).user


def err(fn, *a, **k) -> ApiException:
    with pytest.raises(ApiException) as e:
        fn(*a, **k)
    return e.value


# ---- authentification -------------------------------------------------------
def test_login_errors(svc):
    assert err(svc.login, LoginRequest(email="x@y.z", password="a")).code == "INVALID_CREDENTIALS"
    assert err(svc.login, LoginRequest(email="admin@uge.gov.tn", password="faux")).status == 401


def test_mfa_flow(svc):
    e = err(svc.login, LoginRequest(email="instructeur@uge.gov.tn", password=DEMO_PASSWORD))
    assert (e.status, e.code) == (403, "MFA_REQUIRED")
    e = err(svc.login, LoginRequest(email="instructeur@uge.gov.tn", password=DEMO_PASSWORD, code="000000"))
    assert (e.status, e.code) == (401, "INVALID_CODE")
    assert login(svc, "instructeur@uge.gov.tn", "123456").role == "INSTRUCTOR"
    assert login(svc, "manager@portail.gov.tn").role == "PORTAL_MANAGER"   # pas de code requis


def test_register_pending_and_duplicate(svc):
    u = svc.register(RegisterRequest(name="Nour", email="nour@x.tn", password="motdepasse1"))
    assert (u.status, u.role, u.invited) == ("PENDING", "PORTAL_MANAGER", False)
    assert err(svc.login, LoginRequest(email="nour@x.tn", password="motdepasse1")).code == "ACCOUNT_PENDING"
    assert err(svc.register, RegisterRequest(name="N", email="NOUR@x.tn", password="motdepasse1")).code == "EMAIL_EXISTS"
    svc.set_user_status(u.id, "ACTIVE")
    assert svc.login(LoginRequest(email="nour@x.tn", password="motdepasse1")).token


def test_disabled_account_and_token_revoked(svc):
    resp = svc.login(LoginRequest(email="manager@portail.gov.tn", password=DEMO_PASSWORD))
    svc.set_user_status(resp.user.id, "DISABLED")
    assert err(svc.authenticate, resp.token).code == "UNAUTHORIZED"
    assert err(svc.login, LoginRequest(email="manager@portail.gov.tn", password=DEMO_PASSWORD)).code == "ACCOUNT_DISABLED"


# ---- dossiers ---------------------------------------------------------------
def submit(svc, user, level="WCAG_AA"):
    d = svc.submit(user, SubmitDossierRequest(url="http://localhost/", pages=2, requested_level=level))
    assert d.status == "ANALYZING"
    svc.run_analysis(d.id)
    return d.id


def test_full_dossier_lifecycle(svc):
    manager = login(svc, "manager@portail.gov.tn")
    instr = login(svc, "instructeur@uge.gov.tn", "123456")
    did = submit(svc, manager)
    assert svc.get_dossier(manager, did).status == "ANALYZED"

    assert err(svc.set_label, instr, did, "WCAG_AA").code == "REVIEW_INCOMPLETE"
    assert err(svc.decide_finding, instr, did, 99, "CONFIRMED").code == "NOT_FOUND"
    assert svc.decide_finding(instr, did, 1, "CONFIRMED").status == "ANALYZED"
    d = svc.decide_finding(instr, did, 2, "DISMISSED")
    assert d.status == "REVIEWED"                       # tous les constats ont une décision
    d = svc.set_label(instr, did, "REJECTED")
    assert (d.status, d.label) == ("DECIDED", "REJECTED")
    assert err(svc.set_label, instr, did, "WCAG_AA").code == "ALREADY_DECIDED"
    assert err(svc.decide_finding, instr, did, 1, "CONFIRMED").code == "ALREADY_DECIDED"


def test_visibility(svc):
    m1 = login(svc, "manager@portail.gov.tn")
    m2 = svc.register(RegisterRequest(name="Autre", email="autre@x.tn", password="motdepasse1"))
    svc.set_user_status(m2.id, "ACTIVE")
    m2 = login(svc, "autre@x.tn", password="motdepasse1")
    instr = login(svc, "instructeur@uge.gov.tn", "123456")
    did = submit(svc, m1)
    assert [d.id for d in svc.list_dossiers(m1)] == [did]
    assert svc.list_dossiers(m2) == []
    assert err(svc.get_dossier, m2, did).code == "NOT_FOUND"
    assert [d.id for d in svc.list_dossiers(instr)] == [did]


def test_submit_validation(svc, monkeypatch):
    m = login(svc, "manager@portail.gov.tn")
    assert err(svc.submit, m, SubmitDossierRequest(url="ftp://x", pages=1, requested_level="WCAG_AA")).code == "INVALID_URL"
    assert err(svc.submit, m, SubmitDossierRequest(url="http://x.tn", pages=0, requested_level="WCAG_AA")).code == "VALIDATION_ERROR"
    monkeypatch.setenv("ALLOW_PRIVATE", "0")
    assert err(svc.submit, m, SubmitDossierRequest(url="http://127.0.0.1/", pages=1, requested_level="WCAG_AA")).code == "INVALID_URL"


def test_analysis_failure_never_allows_a_label(monkeypatch):
    monkeypatch.setenv("ALLOW_PRIVATE", "1")

    def boom(*a):
        raise RuntimeError("site injoignable")
    s = Service(Store(), analyze=boom)
    m = s.s.users[2]
    instr = s.s.users[3]
    d = s.submit(m, SubmitDossierRequest(url="http://localhost/", pages=1, requested_level="WCAG_AA"))
    s.run_analysis(d.id)
    assert s.get_dossier(m, d.id).status == "ANALYZED"
    assert "site injoignable" in s.s.errors[d.id]
    assert err(s.set_label, instr, d.id, "WCAG_AA").code == "REVIEW_INCOMPLETE"


def test_zero_findings_is_reviewed(monkeypatch):
    monkeypatch.setenv("ALLOW_PRIVATE", "1")
    s = Service(Store(), analyze=lambda *a: [])
    d = s.submit(s.s.users[2], SubmitDossierRequest(url="http://localhost/", pages=1, requested_level="WCAG_AA"))
    s.run_analysis(d.id)
    assert s.get_dossier(s.s.users[2], d.id).status == "REVIEWED"


# ---- règles -----------------------------------------------------------------
def test_rules_versioning_and_standard(svc):
    aud = login(svc, "auditeur@expert.org", "123456")
    assert err(svc.publish_rules, aud, PublishRulesRequest(contrast_aa=4.0, contrast_aaa=7, min_font_px=12)).code \
        == "RULE_BELOW_STANDARD"
    manager = login(svc, "manager@portail.gov.tn")
    did = submit(svc, manager)                                   # analysé avec la version 1
    r = svc.publish_rules(aud, PublishRulesRequest(contrast_aa=5, contrast_aaa=8, min_font_px=14))
    assert r.version == 2 and svc.current_rules().version == 2
    assert [x.version for x in svc.list_rules()] == [2, 1]       # la plus récente en premier
    assert svc.get_dossier(manager, did).rules_version == 1      # le dossier garde sa version
    assert submit(svc, manager) and svc.get_dossier(manager, 2).rules_version == 2


# ---- utilisateurs, divergences, KPI ----------------------------------------
def test_invitation(svc):
    u = svc.invite(InvitationRequest(name="Sami", email="sami@x.tn", role="INSTRUCTOR"))
    assert (u.invited, u.status, u.role) == (True, "PENDING", "INSTRUCTOR")
    assert err(svc.invite, InvitationRequest(name="S", email="sami@x.tn", role="ADMIN")).code == "EMAIL_EXISTS"


def test_divergences_and_retraining(svc):
    manager = login(svc, "manager@portail.gov.tn")
    instr = login(svc, "instructeur@uge.gov.tn", "123456")
    assert err(svc.retrain).code == "NO_FEEDBACK"
    did = submit(svc, manager)
    svc.decide_finding(instr, did, 1, "CONFIRMED")
    svc.decide_finding(instr, did, 2, "DISMISSED")
    div = svc.divergences()
    assert len(div.false_positives) == 1 and div.false_positives[0].element == "small"
    assert div.false_negatives == []
    kpi = svc.retrain()
    assert kpi.f1_history[0].value == round(2 * 1 / (2 * 1 + 1), 3)   # TP=1, FP=1 -> 0,667
    assert kpi.portals_analysed == 1 and kpi.publications == 1
    assert kpi.model_dump(by_alias=True)["f1History"][0]["month"] == 1
