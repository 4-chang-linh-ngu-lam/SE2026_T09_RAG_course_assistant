from fastapi import FastAPI

from app.common.auth_dependencies import get_user_lookup
from app.modules.health.router import router as health_router
from app.modules.identity.public import get_identity_user_lookup
from app.modules.identity.router import router as identity_router


def register_routers(app: FastAPI) -> None:
    app.dependency_overrides[get_user_lookup] = get_identity_user_lookup
    # Một điểm đăng ký router; các module nghiệp vụ sẽ thêm khi được triển khai.
    app.include_router(health_router)
    app.include_router(identity_router)
