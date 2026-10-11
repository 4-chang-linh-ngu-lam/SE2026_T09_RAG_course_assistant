from fastapi import FastAPI

from app.modules.health.router import router as health_router


def register_routers(app: FastAPI) -> None:
    # Một điểm đăng ký router; các module nghiệp vụ sẽ thêm khi được triển khai.
    app.include_router(health_router)
