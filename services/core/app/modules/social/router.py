from fastapi import APIRouter

from app.modules.social.feed.router import router as feed_router

__all__ = ["router"]

router = APIRouter()
router.include_router(feed_router)
