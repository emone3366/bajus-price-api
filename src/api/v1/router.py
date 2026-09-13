"""
V1 API router — aggregates all v1 route modules.
"""

from fastapi import APIRouter

from src.api.v1.admin import router as admin_router
from src.api.v1.billing import router as billing_router
from src.api.v1.meta import router as meta_router
from src.api.v1.prices import router as prices_router

router = APIRouter(prefix="/v1")

router.include_router(prices_router)
router.include_router(meta_router)
router.include_router(admin_router)
router.include_router(billing_router)
