"""PersonalContext (profil) i Domain (obszary tematyczne) - spec §6.

Zarządzane ręcznie przez użytkownika (ekran ustawień) - spec nie definiuje
automatycznego wyprowadzania domen/kontekstu, więc to prosty CRUD.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Domain, PersonalContext

router = APIRouter(prefix="/api/profile", tags=["profile"])


class PersonalContextBody(BaseModel):
    content: str


@router.get("/personal-context")
def get_personal_context(db: Session = Depends(get_db)):
    ctx = (
        db.query(PersonalContext)
        .filter(PersonalContext.active.is_(True))
        .order_by(PersonalContext.version.desc())
        .first()
    )
    return {"content": ctx.content if ctx else "", "version": ctx.version if ctx else 0}


@router.put("/personal-context")
def set_personal_context(body: PersonalContextBody, db: Session = Depends(get_db)):
    content = body.content.strip()
    prev = (
        db.query(PersonalContext)
        .filter(PersonalContext.active.is_(True))
        .order_by(PersonalContext.version.desc())
        .first()
    )
    if prev is not None:
        prev.active = False
    ctx = PersonalContext(version=(prev.version + 1) if prev else 1, content=content, active=True)
    db.add(ctx)
    db.commit()
    return {"content": ctx.content, "version": ctx.version}


class DomainBody(BaseModel):
    name: str
    target_sessions: int = 5


SUGGESTED_DOMAINS = [
    "remote work",
    "travel",
    "cooking",
    "home renovation",
    "personal finance",
    "fitness",
    "parenting",
    "career change",
    "moving abroad",
    "startups",
]


@router.get("/domains/suggestions")
def suggest_domains(db: Session = Depends(get_db)):
    """Podpowiedzi tematów do wyboru, z pominięciem tych już użytych."""
    used = {d.name.strip().lower() for d in db.query(Domain).all()}
    return [name for name in SUGGESTED_DOMAINS if name not in used]


@router.get("/domains")
def list_domains(db: Session = Depends(get_db)):
    rows = db.query(Domain).order_by(Domain.id.desc()).all()
    return [
        {
            "id": d.id,
            "name": d.name,
            "status": d.status,
            "session_count": d.session_count,
            "target_sessions": d.target_sessions,
            "started_at": d.started_at,
        }
        for d in rows
    ]


@router.post("/domains")
def create_domain(body: DomainBody, db: Session = Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Brak nazwy domeny")
    if not 1 <= body.target_sessions <= 20:
        raise HTTPException(422, "target_sessions poza rozsądnym zakresem 1-20")
    existing_active = db.query(Domain).filter(Domain.status == "active").first()
    if existing_active is not None:
        raise HTTPException(409, f"Domena '{existing_active.name}' jest już aktywna - dokończ ją albo oznacz jako zakończoną")
    domain = Domain(name=name, target_sessions=body.target_sessions)
    db.add(domain)
    db.commit()
    return {"id": domain.id, "name": domain.name}


@router.post("/domains/{domain_id}/finish")
def finish_domain(domain_id: int, db: Session = Depends(get_db)):
    """Ręczne domknięcie domeny wcześniej niż target_sessions, jeśli użytkownik chce zmienić temat."""
    domain = db.get(Domain, domain_id)
    if domain is None:
        raise HTTPException(404, "Nie ma takiej domeny")
    domain.status = "done"
    db.commit()
    return {"ok": True}


@router.post("/domains/{domain_id}/reactivate")
def reactivate_domain(domain_id: int, db: Session = Depends(get_db)):
    """Powrót do wcześniej zakończonej domeny (spec §6 nie wyklucza wznowienia)."""
    domain = db.get(Domain, domain_id)
    if domain is None:
        raise HTTPException(404, "Nie ma takiej domeny")
    existing_active = db.query(Domain).filter(Domain.status == "active").first()
    if existing_active is not None and existing_active.id != domain.id:
        raise HTTPException(409, f"Domena '{existing_active.name}' jest już aktywna - dokończ ją albo oznacz jako zakończoną")
    if domain.session_count >= domain.target_sessions:
        domain.target_sessions = domain.session_count + 5
    domain.status = "active"
    db.commit()
    return {"ok": True}
