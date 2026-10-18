from fastapi import FastAPI

from app.common.auth_dependencies import get_user_lookup
from app.modules.administration.router import router as administration_router
from app.modules.classroom.router import internal_router as classroom_internal_router
from app.modules.classroom.router import router as classroom_router
from app.modules.health.router import router as health_router
from app.modules.identity.public import get_identity_user_lookup
from app.modules.identity.router import router as identity_router
from app.modules.notification.router import router as notification_router
from app.modules.social.router import router as social_router


def register_routers(app: FastAPI) -> None:
    app.dependency_overrides[get_user_lookup] = get_identity_user_lookup
    # Một điểm đăng ký router; các module nghiệp vụ sẽ thêm khi được triển khai.
    app.include_router(health_router)
    app.include_router(identity_router)
    app.include_router(classroom_router)
    app.include_router(classroom_internal_router)
    app.include_router(social_router)
    app.include_router(notification_router)
    app.include_router(administration_router)
