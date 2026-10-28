"""Offline maintenance owned by Identity; never registered as HTTP onboarding."""

from collections import Counter
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import SecretStr, TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.audit import AuditMetadata, record_audit
from app.common.security import generate_refresh_token, hash_password
from app.modules.identity.models import Role, RoleAssignment, User, UserStatus
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.schemas import (
    ActivateStudentRequest,
    AdminCreateStudentRequest,
    AdminCreateUserRequest,
    ResetPasswordRequest,
    Username,
)
from app.modules.identity.service import IdentityService


def maintenance_identity_report(*, session: Session) -> list[dict]:
    """Identifiers and migration issues only: no email, credential or request content."""
    users = list(
        session.scalars(select(User).order_by(User.id).execution_options(populate_existing=True))
    )
    roles = {}
    for user_id, role in session.execute(select(RoleAssignment.user_id, RoleAssignment.role)):
        roles.setdefault(user_id, set()).add(role)
    normalized = {}
    for user in users:
        if user.username is not None:
            try:
                normalized[user.id] = TypeAdapter(Username).validate_python(user.username)
            except ValidationError:
                pass
    counts = Counter(normalized.values())
    report = []
    for user in users:
        issues = []
        if user.school_id is None:
            issues.append("MISSING_SCHOOL_SCOPE")
        if user.username is not None:
            if normalized.get(user.id) != user.username:
                issues.append("INVALID_USERNAME")
            if counts[normalized.get(user.id)] > 1:
                issues.append("DUPLICATE_USERNAME")
        if Role.STUDENT in roles.get(user.id, set()):
            if user.username is None:
                issues.append("STUDENT_USERNAME_NOT_MIGRATED")
            if user.activated_at is None:
                issues.append("STUDENT_ACTIVATION_PENDING")
        report.append(
            {
                "user_id": str(user.id),
                "school_id": str(user.school_id) if user.school_id else None,
                "status": str(user.status),
                "roles": sorted(str(role) for role in roles.get(user.id, set())),
                "session_version": user.session_version,
                "updated_at": user.updated_at.isoformat(),
                "issues": issues,
            }
        )
    return report


def maintenance_assign_school(
    assignments: dict[UUID, UUID], *, session: Session, correlation_id: UUID
) -> None:
    """Only fill approved missing scopes; credentials/status/history remain intact."""
    service = IdentityService(session)
    users = IdentityRepository(session).lock_users(sorted(assignments))
    for user_id, school_id in sorted(assignments.items()):
        user = users.get(user_id)
        if user is None or user.school_id not in (None, school_id):
            raise ValueError("Unknown account or cross-school reassignment; review mapping")
        if user.school_id == school_id:
            continue
        user.school_id = school_id
        service._revoke_all(user)
        record_audit(
            session,
            actor_id=None,
            school_id=school_id,
            action="LEGACY_ASSIGN_SCHOOL",
            target_type="USER",
            target_id=user_id,
            correlation_id=correlation_id,
            metadata_json=AuditMetadata(
                changed_fields=["school_id"], reason_code="ADMIN_INTERVENTION"
            ),
        )
    session.flush()


def bootstrap_dev_identity(*, school_id: UUID, admin_password: SecretStr, session: Session) -> dict:
    """Fixture bootstrap for an exclusively locked, empty dev/test DB only.

    The maintenance coordinator enforces that boundary. First Admin is the only
    direct bootstrap; subsequent staff and Students redeem normal one-time flows.
    Generated per-account passwords/codes are discarded and never returned.
    """
    if session.scalar(select(User.id).limit(1)) is not None:
        raise ValueError("Development Identity bootstrap requires an empty database")
    if not 12 <= len(admin_password.get_secret_value()) <= 128:
        raise ValueError("Provide a unique Admin password of 12–128 characters")
    admin = User(
        email="admin@seed.example.com",
        school_id=school_id,
        password_hash=hash_password(admin_password.get_secret_value()),
        status=UserStatus.ACTIVE,
        email_verified_at=datetime.now(UTC),
    )
    session.add(admin)
    session.flush()
    session.add(RoleAssignment(user_id=admin.id, role=Role.ADMIN))
    session.flush()
    service = IdentityService(session)
    lecturers = []
    for name in ("primary", "assisting"):
        lecturer, invitation = service.admin_create_user(
            AdminCreateUserRequest(email=f"{name}@seed.example.com", roles=[Role.LECTURER]),
            actor_id=admin.id,
            correlation_id=uuid4(),
        )
        service.reset_password(
            ResetPasswordRequest(
                token=invitation.token, new_password=SecretStr(generate_refresh_token())
            ),
            commit=False,
        )
        lecturers.append(lecturer.id)
    students = []
    for index in range(1, 4):
        username = f"seed.student.{index}"
        code = service.admin_create_student(
            AdminCreateStudentRequest(username=username), actor_id=admin.id, correlation_id=uuid4()
        )
        if index < 3:
            service.activate_student(
                ActivateStudentRequest(
                    username=username,
                    activation_code=code.code,
                    new_password=SecretStr(generate_refresh_token()),
                ),
                correlation_id=uuid4(),
                commit=False,
            )
        students.append(code.student.id)
    session.flush()
    return {"admin_id": admin.id, "lecturer_ids": lecturers, "student_ids": students}
