from fastapi import APIRouter

from app.modules.social.calendar.router import router as calendar_router
from app.modules.social.comments.router import router as comments_router
from app.modules.social.feed.router import router as feed_router

__all__ = ["router"]

router = APIRouter()
router.include_router(feed_router)
router.include_router(comments_router)
router.include_router(calendar_router)
