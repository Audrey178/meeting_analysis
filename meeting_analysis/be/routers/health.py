from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Kiểm tra dịch vụ còn sống (dùng cho load balancer/giám sát); luôn trả ``{"status": "ok"}``."""

    return {"status": "ok"}
