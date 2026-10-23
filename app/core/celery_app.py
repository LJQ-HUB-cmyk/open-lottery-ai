# -*- coding: utf-8 -*-
"""
Celery 应用配置。broker 与 result backend 均由配置注入（默认 Redis），
结果后端必须使用 Redis（不可用 RPC），避免结果查询阻塞。
"""
from celery import Celery
from celery.schedules import crontab

from .config import settings

celery_app = Celery(
    "lottery_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.training_jobs", "app.tasks.evolution_jobs"]
)

# ---------- 自我进化闭环定时调度（Celery Beat） ----------
# 每日定时触发；任务内部有「新数据闸门」，无新数据会自动跳过，避免空跑。
_beat_schedule = {}
if settings.SELF_EVOLVE_ENABLED:
    for lt in ("ssq", "dlt"):
        _beat_schedule[f"self-evolve-{lt}"] = {
            "task": "app.tasks.evolution_jobs.run_self_evolution",
            "schedule": crontab(
                hour=settings.SELF_EVOLVE_HOUR,
                minute=settings.SELF_EVOLVE_MINUTE,
            ),
            "args": (lt,),
        }

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_time_limit=7200,          # 2 小时硬超时
    task_soft_time_limit=6900,     # 软超时（提前 5 分钟）
    worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,  # worker 并发进程数
    worker_prefetch_multiplier=1,  # 训练任务重，避免一个 worker 预取过多任务堆积
    task_acks_late=True,           # 任务执行完成后才 ack，worker 崩溃可重投
    timezone="Asia/Shanghai",      # Beat crontab 按本地时区解析
    beat_schedule=_beat_schedule,
)
