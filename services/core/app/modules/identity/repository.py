from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.modules.identity.models import (
    AuthSession,
    DataRequest,
    OneTimeToken,
    RoleAssignment,
    TokenPurpose,
    User,
)
from app.modules.identity.schemas import UserProfile, UserSummaryDTO


class IdentityRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_by_username(self, username: str, *, for_update: bool = False) -> User | None:
        query = select(User).where(User.username == username)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def get_by_email(self, email: str, *, for_update: bool = False) -> User | None:
        query = select(User).where(User.email == email.lower())
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def get_users_summaries(self, user_ids: list[UUID]) -> dict[UUID, UserSummaryDTO]:
        if not user_ids:
            return {}
        rows = self.session.execute(
            select(
                User.id, User.email, User.username, User.school_id, User.display_name, User.status
            ).where(User.id.in_(user_ids))
        ).all()
        return {
            row.id: UserSummaryDTO(
                id=row.id,
                email=row.email,
                username=row.username,
                school_id=row.school_id,
                display_name=row.display_name,
                status=row.status,
            )
            for row in rows
        }

    def lock_users(self, user_ids: list[UUID]) -> dict[UUID, User]:
        users = self.session.scalars(
            select(User)
            .where(User.id.in_(user_ids))
            .order_by(User.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return {user.id: user for user in users}

    def create_data_request(self, data_request: DataRequest) -> DataRequest:
        self.session.add(data_request)
        self.session.flush()
        return data_request

    def list_data_requests(
        self, user_id: UUID, limit: int, cursor: UUID | None
    ) -> list[DataRequest]:
        query = select(DataRequest).where(DataRequest.user_id == user_id)
        if cursor is not None:
            query = query.where(DataRequest.id > cursor)
        return list(self.session.scalars(query.order_by(DataRequest.id).limit(limit + 1)))

    def get_profile(self, user_id: UUID) -> UserProfile | None:
        rows = self.session.execute(
            select(
                User.id,
                User.email,
                User.username,
                User.school_id,
                User.display_name,
                User.status,
                RoleAssignment.role,
            )
            .outerjoin(RoleAssignment, RoleAssignment.user_id == User.id)
            .where(User.id == user_id)
        ).all()
        if not rows:
            return None
        user = rows[0]
        return UserProfile(
            id=user.id,
            email=user.email,
            username=user.username,
            school_id=user.school_id,
            display_name=user.display_name,
            status=user.status,
            roles=sorted(row.role for row in rows if row.role),
        )

    def get_by_id(self, user_id: UUID, *, for_update: bool = False) -> User | None:
        query = select(User).where(User.id == user_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def create_user(self, user: User) -> User:
        self.session.add(user)
        self.session.flush()
        return user

    def get_user_roles(self, user_id: UUID) -> list[str]:
        return list(
            self.session.scalars(
                select(RoleAssignment.role)
                .where(RoleAssignment.user_id == user_id)
                .order_by(RoleAssignment.role)
            )
        )

    def create_session(self, session: AuthSession) -> AuthSession:
        self.session.add(session)
        self.session.flush()
        return session

    def get_session_by_refresh_hash(
        self, refresh_hash: str, *, for_update: bool = False
    ) -> AuthSession | None:
        query = select(AuthSession).where(AuthSession.refresh_hash == refresh_hash)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def revoke_session_family(self, family_id: UUID, now: datetime) -> None:
        self.session.execute(
            update(AuthSession)
            .where(AuthSession.family_id == family_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    def revoke_all_user_sessions(self, user_id: UUID, now: datetime) -> None:
        self.session.execute(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    def create_one_time_token(self, token: OneTimeToken) -> OneTimeToken:
        self.session.add(token)
        self.session.flush()
        return token

    def get_one_time_token(
        self,
        token_hash: str,
        purpose: TokenPurpose | tuple[TokenPurpose, ...],
        *,
        for_update: bool = False,
    ) -> OneTimeToken | None:
        query = select(OneTimeToken).where(
            OneTimeToken.token_hash == token_hash,
            OneTimeToken.purpose.in_(purpose if isinstance(purpose, tuple) else (purpose,)),
        )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def consume_one_time_token(self, token: OneTimeToken, now: datetime) -> None:
        token.consumed_at = now

    def invalidate_one_time_tokens(
        self, user_id: UUID, purpose: TokenPurpose, now: datetime
    ) -> None:
        self.session.execute(
            update(OneTimeToken)
            .where(
                OneTimeToken.user_id == user_id,
                OneTimeToken.purpose == purpose,
                OneTimeToken.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
