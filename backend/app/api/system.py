"""System routes."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
