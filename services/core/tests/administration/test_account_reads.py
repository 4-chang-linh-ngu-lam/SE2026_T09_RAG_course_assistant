"""School-scoped read contracts use real PostgreSQL and authoritative Identity state."""

from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, update

from app.common.audit import AuditEvent
from app.common.errors import AppError
from app.common.pagination import Pagination, encode_cursor
from app.modules.identity import public as identity
from app.modules.identity.models import Role, RoleAssignment, User, UserStatus

ACCOUNT_FIELDS = {"id", "email", "username", "school_id", "display_name", "status", "roles"}


def read_headers(system, name="admin"):
    return {key: value for key, value in system.headers(name).items() if key != "X-Admin-Reason"}


def test_account_pages_are_complete_scoped_safe_and_do_not_mutate(system):
    teacher = system.users["teacher"]
    with system.factory.begin() as db:
        db.add(RoleAssignment(user_id=teacher.id, role=Role.ADMIN))
        db.execute(update(User).where(User.id == teacher.id).values(display_name=None))
        before = db.scalar(select(func.count()).select_from(AuditEvent))
    items, cursor = [], None
    for _ in range(5):
        params = {"limit": 1, **({"cursor": cursor} if cursor else {})}
        response = system.client.get(
            "/api/v1/admin/users", params=params, headers=read_headers(system)
        )
        assert response.status_code == 200, response.text
        assert response.headers["Cache-Control"] == "no-store"
        page = response.json()
        assert set(page) == {"items", "next_cursor"} and len(page["items"]) == 1
        items.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert len(cursor) == 22
    assert cursor is None
    expected = {str(system.users[name].id) for name in ("admin", "admin2", "teacher", "student")}
    assert {item["id"] for item in items} == expected
    assert len(items) == len(expected)
    assert [item["id"] for item in items] == sorted(expected)
    for item in items:
        assert set(item) == ACCOUNT_FIELDS
        assert item["school_id"] == str(system.school_id)
    student = next(item for item in items if item["id"] == str(system.users["student"].id))
    assert student["email"] is None and student["username"] is not None
    assert student["roles"] == ["STUDENT"]
    current_teacher = next(item for item in items if item["id"] == str(teacher.id))
    assert current_teacher["username"] is None and current_teacher["display_name"] is None
    assert current_teacher["roles"] == ["ADMIN", "LECTURER"]
    detail = system.client.get(f"/api/v1/admin/users/{teacher.id}", headers=read_headers(system))
    assert detail.status_code == 200 and detail.json() == current_teacher
    assert detail.headers["Cache-Control"] == "no-store"
    with system.factory() as db:
        assert db.scalar(select(func.count()).select_from(AuditEvent)) == before


def test_account_read_cursor_and_detail_cannot_cross_school_or_null_scope(system):
    for target_id in (
        system.users["other_student"].id,
        system.users["unscoped"].id,
        uuid4(),
    ):
        for path in (
            f"/api/v1/admin/users/{target_id}",
            f"/api/v1/admin/users?cursor={encode_cursor(target_id)}",
        ):
            response = system.client.get(path, headers=read_headers(system))
            assert response.status_code == 404
            assert response.headers["Cache-Control"] == "no-store"
    # A browser's supplied school does not replace the actor's current school.
    response = system.client.get(
        "/api/v1/admin/users",
        params={"school_id": str(system.users["other_student"].school_id)},
        headers=read_headers(system),
    )
    assert response.status_code == 200
    assert {item["school_id"] for item in response.json()["items"]} == {str(system.school_id)}
    for path in ("/api/v1/admin/users", f"/api/v1/admin/users/{system.users['admin'].id}"):
        assert system.client.get(path, headers=read_headers(system, "unscoped")).status_code == 404


@pytest.mark.parametrize(
    "query,status",
    [
        ("limit=0", 422),
        ("limit=101", 422),
        ("limit=a", 422),
        ("cursor=invalid", 400),
        ("cursor=AAAAAAAAAAAAAAAAAAAAAB", 400),
    ],
)
def test_account_read_pagination_rejects_invalid_wire_values(system, query, status):
    response = system.client.get("/api/v1/admin/users?" + query, headers=read_headers(system))
    assert response.status_code == status
    assert response.headers["Cache-Control"] == "no-store"


def test_account_reads_check_current_roles_status_and_revocation(system):
    path = f"/api/v1/admin/users/{system.users['student'].id}"
    for route in ("/api/v1/admin/users", path):
        assert system.client.get(route).status_code == 401
        for name in ("teacher", "student"):
            assert system.client.get(route, headers=read_headers(system, name)).status_code == 403
    old_headers = read_headers(system)
    admin_id = system.users["admin"].id
    with system.factory.begin() as db:
        db.execute(delete(RoleAssignment).where(RoleAssignment.user_id == admin_id))
        db.add(RoleAssignment(user_id=admin_id, role=Role.LECTURER))
    for route in ("/api/v1/admin/users", path):
        assert system.client.get(route, headers=old_headers).status_code == 403
    with system.factory.begin() as db:
        db.execute(delete(RoleAssignment).where(RoleAssignment.user_id == admin_id))
        db.add(RoleAssignment(user_id=admin_id, role=Role.ADMIN))
        db.execute(update(User).where(User.id == admin_id).values(status=UserStatus.LOCKED))
    for route in ("/api/v1/admin/users", path):
        assert system.client.get(route, headers=old_headers).status_code == 401
    with system.factory.begin() as db:
        db.execute(
            update(User)
            .where(User.id == admin_id)
            .values(status=UserStatus.ACTIVE, session_version=User.session_version + 1)
        )
    for route in ("/api/v1/admin/users", path):
        assert system.client.get(route, headers=old_headers).status_code == 401


def test_account_reads_reconcile_current_status_roles_and_public_dtos(system):
    teacher = system.users["teacher"]
    path = f"/api/v1/admin/users/{teacher.id}"
    first = system.client.get(path, headers=read_headers(system)).json()
    assert first["status"] == "ACTIVE" and first["roles"] == ["LECTURER"]
    locked = system.client.patch(
        path + "/status", json={"status": "LOCKED"}, headers=system.headers()
    )
    assert locked.status_code == 204
    roles = system.client.put(
        path + "/roles", json={"roles": ["ADMIN", "LECTURER"]}, headers=system.headers()
    )
    assert roles.status_code == 200 and "roles" not in roles.json()
    current = system.client.get(path, headers=read_headers(system))
    assert current.status_code == 200
    assert current.json()["status"] == "LOCKED"
    assert current.json()["roles"] == ["ADMIN", "LECTURER"]
    with system.factory() as db:
        dto = identity.admin_get_user(teacher.id, actor_id=system.users["admin"].id, session=db)
        assert isinstance(dto, identity.AdminUserReadDTO)
        assert dto.model_dump(mode="json") == current.json()
        page = identity.admin_list_users(
            Pagination(limit=100, cursor=None), actor_id=system.users["admin"].id, session=db
        )
        assert all(isinstance(item, identity.AdminUserReadDTO) for item in page.items)
        assert set(dto.model_dump()) == ACCOUNT_FIELDS
        assert page.next_cursor is None


def test_account_list_default_limit_and_unassigned_legacy_roles_are_not_fabricated(system):
    ids = [uuid4() for _ in range(21)]
    with system.factory.begin() as db:
        db.add_all(
            User(
                id=id,
                school_id=system.school_id,
                email=f"{id}@example.com",
                password_hash="synthetic-noncredential-hash",
                status=UserStatus.PENDING_VERIFICATION,
            )
            for id in ids
        )
    first = system.client.get("/api/v1/admin/users", headers=read_headers(system))
    assert first.status_code == 200
    assert len(first.json()["items"]) == 20 and first.json()["next_cursor"] is not None
    full = system.client.get("/api/v1/admin/users?limit=100", headers=read_headers(system))
    assert full.status_code == 200 and len(full.json()["items"]) == 25
    assert full.json()["next_cursor"] is None
    legacy = system.client.get(f"/api/v1/admin/users/{ids[0]}", headers=read_headers(system)).json()
    assert legacy["roles"] == [] and legacy["status"] == "PENDING_VERIFICATION"
    assert legacy["display_name"] is None and legacy["username"] is None


def test_public_account_read_rechecks_school_and_status_with_cached_actor(system):
    actor_id, target_id = system.users["admin"].id, system.users["student"].id
    with system.factory() as db:
        cached_actor = db.get(User, actor_id)
        assert identity.admin_get_user(target_id, actor_id=actor_id, session=db).id == target_id
        with system.factory.begin() as concurrent:
            concurrent.execute(update(User).where(User.id == actor_id).values(school_id=uuid4()))
        assert cached_actor.school_id == system.school_id
        with pytest.raises(AppError) as outside_school:
            identity.admin_get_user(target_id, actor_id=actor_id, session=db)
        assert outside_school.value.status_code == 404
        with system.factory.begin() as concurrent:
            concurrent.execute(
                update(User)
                .where(User.id == actor_id)
                .values(school_id=system.school_id, status=UserStatus.LOCKED)
            )
        assert cached_actor.status == UserStatus.ACTIVE
        with pytest.raises(AppError) as locked:
            identity.admin_list_users(
                Pagination(limit=20, cursor=None), actor_id=actor_id, session=db
            )
        assert locked.value.status_code == 403
