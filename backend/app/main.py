"""Routes FastAPI : fines enveloppes autour de services.Service, conformes au contrat d'API de l'équipe frontend.

Lancer :  cd backend && PYTHONPATH=. uvicorn app.main:app --reload     (docs interactives : /docs)
"""
from __future__ import annotations

import os

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .errors import ApiException
from .models import (DecisionUpdate, Divergences, Dossier, InvitationRequest, Kpi, LabelUpdate, LoginRequest,
                     LoginResponse, PublishRulesRequest, RegisterRequest, Rules, StatusUpdate,
                     SubmitDossierRequest, User)
from .services import Service

app = FastAPI(title="IA-Audit-Auto", version="0.2.0")
svc = Service()

# Angular en développement : ng serve écoute sur http://localhost:4200
origins = os.environ.get("CORS_ORIGINS", "http://localhost:4200").split(",")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(ApiException)
async def _api_error(_: Request, exc: ApiException):
    return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message})


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(x) for x in first.get("loc", [])[1:])
    return JSONResponse(status_code=400, content={"code": "VALIDATION_ERROR",
                                                  "message": f"Requête invalide ({where}) : {first.get('msg', '')}"})


# ---------------------------------------------------------------- sécurité
def current_user(authorization: str | None = Header(default=None)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiException(401, "UNAUTHORIZED", "Authentification requise.")
    return svc.authenticate(authorization[7:].strip())


def roles(*allowed: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise ApiException(403, "FORBIDDEN", "Accès refusé pour votre rôle.")
        return user
    return dep


# `exclude_none` : les champs optionnels vides sont omis (le frontend attend `label?:`, pas `label: null`).
OPT = {"response_model_exclude_none": True}
api = APIRouter(prefix="/api")


@api.get("/health")
def health():
    return {"status": "ok"}


# -------------------------------------------------------------------- auth
@api.post("/auth/login", response_model=LoginResponse, **OPT)
def login(req: LoginRequest):
    return svc.login(req)


@api.post("/auth/register", response_model=User, status_code=201, **OPT)
def register(req: RegisterRequest):
    return svc.register(req)


# ---------------------------------------------------------------- dossiers
@api.get("/dossiers", response_model=list[Dossier], **OPT)
def list_dossiers(user: User = Depends(roles("PORTAL_MANAGER", "INSTRUCTOR"))):
    return svc.list_dossiers(user)


@api.get("/dossiers/{dossier_id}", response_model=Dossier, **OPT)
def get_dossier(dossier_id: int, user: User = Depends(roles("PORTAL_MANAGER", "INSTRUCTOR"))):
    return svc.get_dossier(user, dossier_id)


@api.post("/dossiers", response_model=Dossier, status_code=201, **OPT)
def submit_dossier(req: SubmitDossierRequest, background: BackgroundTasks,
                   user: User = Depends(roles("PORTAL_MANAGER"))):
    dossier = svc.submit(user, req)
    background.add_task(svc.run_analysis, dossier.id)  # l'analyse tourne après l'envoi de la réponse
    return dossier


@api.patch("/dossiers/{dossier_id}/findings/{finding_id}", response_model=Dossier, **OPT)
def decide_finding(dossier_id: int, finding_id: int, body: DecisionUpdate,
                   user: User = Depends(roles("INSTRUCTOR"))):
    return svc.decide_finding(user, dossier_id, finding_id, body.decision)


@api.post("/dossiers/{dossier_id}/label", response_model=Dossier, **OPT)
def set_label(dossier_id: int, body: LabelUpdate, user: User = Depends(roles("INSTRUCTOR"))):
    return svc.set_label(user, dossier_id, body.label)


# ------------------------------------------------------------------ règles
@api.get("/rules/current", response_model=Rules, **OPT)
def current_rules(_: User = Depends(roles("WCAG_AUDITOR", "ADMIN"))):
    return svc.current_rules()


@api.get("/rules", response_model=list[Rules], **OPT)
def list_rules(_: User = Depends(roles("WCAG_AUDITOR", "ADMIN"))):
    return svc.list_rules()


@api.post("/rules", response_model=Rules, status_code=201, **OPT)
def publish_rules(req: PublishRulesRequest, user: User = Depends(roles("WCAG_AUDITOR"))):
    return svc.publish_rules(user, req)


# ------------------------------------------------------------ utilisateurs
@api.get("/users", response_model=list[User], **OPT)
def list_users(_: User = Depends(roles("ADMIN"))):
    return svc.list_users()


@api.post("/users/invitations", response_model=User, status_code=201, **OPT)
def invite(req: InvitationRequest, _: User = Depends(roles("ADMIN"))):
    return svc.invite(req)


@api.patch("/users/{user_id}", response_model=User, **OPT)
def set_user_status(user_id: int, body: StatusUpdate, _: User = Depends(roles("ADMIN"))):
    return svc.set_user_status(user_id, body.status)


# ------------------------------------------------------------- statistiques
@api.get("/divergences", response_model=Divergences, **OPT)
def divergences(_: User = Depends(roles("WCAG_AUDITOR", "JUNIOR_AUDITOR"))):
    return svc.divergences()


@api.get("/kpi", response_model=Kpi, **OPT)
def kpi(_: User = Depends(roles("ADMIN"))):
    return svc.kpi()


@api.post("/models/retraining", response_model=Kpi, **OPT)
def retraining(_: User = Depends(roles("ADMIN"))):
    return svc.retrain()


app.include_router(api)
