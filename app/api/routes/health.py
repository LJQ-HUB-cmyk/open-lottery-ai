# -*- coding: utf-8 -*-
"""健康检查接口"""
from fastapi import APIRouter, Request

router = APIRouter(tags=["Health"])

@router.get("/health")
async def health_check(request: Request):
    """返回服务健康状态 + DB 可用性"""
    db_ok = getattr(request.app.state, "db_available", None)
    return {
        "status": "ok",
        "service": "lottery-backend",
        "version": "1.0.0",
        "database": db_ok,  # True / False / None(未探测)
    }