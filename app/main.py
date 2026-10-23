# -*- coding: utf-8 -*-
"""
FastAPI 应用入口，注册路由、中间件和生命周期事件。
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import health, data, train, predict, models, analysis, agent, hit_analysis
from app.core.config import settings
from app.core.database import engine, Base
from app.core.migrations import run_migrations
from app.models.model_score import ModelScore  # noqa: F401 确保建表元数据注册
from app.models.hit_analysis import HitAnalysis  # noqa: F401

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期：启动时探测 DB + 建表 + 幂等迁移；关闭时释放连接池。
    DB 不可用时仅打警告不退出，让服务本身先起来——健康检查和业务接口会各自反映 DB 状态。
    """
    db_ok = False
    try:
        # 用短超时探测 DB 是否可达（asyncmy 连接默认可能等 30s）
        await asyncio.wait_for(engine.connect(), timeout=10.0)
        async with engine.begin() as conn:
            # create_all 只创建不存在的表；已存在表的新列/索引交给 run_migrations 补齐
            await conn.run_sync(Base.metadata.create_all)
        migrated = await asyncio.to_thread(run_migrations)
        if migrated["added_columns"]:
            print(f"✅ 迁移补齐列：{', '.join(migrated['added_columns'])}")
        if migrated["added_indexes"]:
            print(f"✅ 迁移补齐索引：{', '.join(migrated['added_indexes'])}")
        print("✅ 数据库连接成功，表结构已就绪")
        db_ok = True
    except asyncio.TimeoutError:
        logger.warning("⚠️ 数据库连接超时（10s），服务继续启动但 DB 相关接口会失败")
        print("⚠️ 数据库连接超时，服务继续启动 —— 业务接口会在首次调用时报 DB 错误")
    except Exception as e:
        logger.warning("⚠️ 数据库连接失败：%s，服务继续启动", e)
        print(f"⚠️ 数据库连接失败：{e} —— 服务继续启动，检查 MySQL 是否运行、账号密码是否正确")
    finally:
        # 在 app.state 里挂个标记，让 /health 能读
        app.state.db_available = db_ok

    yield

    # 关闭阶段：只有 DB 真连上过才 dispose，否则避免对未建立的池做多余动作
    if db_ok:
        await engine.dispose()
        print("🛑 数据库连接已关闭")


app = FastAPI(
    title="Open-Lottery-AI",
    description="基于 PyTorch + Transformer 的号码预测系统后端",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS：显式列出允许来源（来自配置），避免 "*" 与 credentials 同时使用的非法组合
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(health.router)
app.include_router(data.router)
app.include_router(train.router)
app.include_router(predict.router)
app.include_router(models.router)
app.include_router(analysis.router)
app.include_router(agent.router)
app.include_router(hit_analysis.router)
