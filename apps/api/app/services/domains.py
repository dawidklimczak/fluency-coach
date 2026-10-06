"""Domeny tematyczne (spec §6): jedna aktywna naraz, trwa target_sessions sesji."""

from sqlalchemy.orm import Session

from ..models import Domain


def get_active_domain(db: Session) -> Domain | None:
    return (
        db.query(Domain)
        .filter(Domain.status == "active")
        .order_by(Domain.id.desc())
        .first()
    )


def advance_domain_after_session(db: Session, domain: Domain) -> None:
    domain.session_count += 1
    if domain.session_count >= domain.target_sessions:
        domain.status = "done"
    db.commit()
