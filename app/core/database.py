# -*- coding: utf-8 -*-
"""
数据库异步引擎与会话管理。
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from .config import settings

# 创建异步引擎
engine = create_async_engine(
    settings.mysql_url,
    echo=False,                  # 生产环境建议关闭 SQL 日志
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True
)

# 异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# ORM 基类
Base = declarative_base()

async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：获取数据库会话"""
    async with AsyncSessionLocal() as session:
        yield session