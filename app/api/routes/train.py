# -*- coding: utf-8 -*-
"""
模型训练接口：提交训练任务、查询训练状态、获取推荐参数。
"""
import asyncio

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, Query

from app.core.celery_app import celery_app
from app.schemas.lottery import TrainRequest, TrainResponse, EvolveRequest
from app.tasks.training_jobs import start_training, run_full_pipeline
from app.tasks.evolution_jobs import run_self_evolution
from app.services.backtest_service import (
    get_top_hyperparams, get_top_models, sample_recommended_params,
)

router = APIRouter(prefix="/train", tags=["Training"])

@router.get("/recommended-params")
async def get_recommended_params(
    lottery_type: str = Query('ssq', description="彩种：ssq 或 dlt")
):
    """
    获取推荐训练参数（基于 P2 高命中率模型超参分布）。
    返回超参区间 + Top 模型回测得分 + 一组采样参数供直接使用。
    无回测数据时返回 has_recommendation=False，前端应回退到手动输入。
    """
    if lottery_type not in ('ssq', 'dlt'):
        raise HTTPException(status_code=400, detail="lottery_type 必须是 ssq 或 dlt")

    hyperparams = await asyncio.to_thread(get_top_hyperparams, lottery_type)
    top_model_names = await asyncio.to_thread(get_top_models, lottery_type, 10)
    sampled = await asyncio.to_thread(sample_recommended_params, lottery_type)

    return {
        "lottery_type": lottery_type,
        "has_recommendation": sampled is not None,
        "hyperparams": hyperparams if hyperparams else None,
        "sampled_params": sampled,
        "top_models": top_model_names,
    }


@router.post("/evolve")
async def start_evolve(request: EvolveRequest):
    """
    手动触发一轮自我进化闭环（不等 Celery Beat 定时）。
    流程：抓取/检测新数据 → 回测 → 采样高命中率参数 → 批量训练 → 复测 → 晋升 → 集成预测入库。
    force=True 时忽略「无新数据」闸门强制跑一轮。
    """
    if request.lottery_type not in ('ssq', 'dlt'):
        raise HTTPException(status_code=400, detail="lottery_type 必须是 ssq 或 dlt")
    task = run_self_evolution.delay(
        lottery_type=request.lottery_type,
        n_models=request.n_models,
        force=request.force,
    )
    return {
        "task_id": task.id,
        "status": "pending",
        "message": "自我进化任务已提交",
    }


@router.post("/start", response_model=TrainResponse)
async def start_train(request: TrainRequest):
    """
    启动异步训练任务。
    auto_params=True 时从高命中率模型超参区间采样 epochs/batch_size/learning_rate，
    采样失败回退到请求中的默认值。
    提交后立即返回 task_id，用于后续查询进度。
    若 with_fetch=True，则先执行数据抓取再训练。
    """
    lottery_type = request.lottery_type
    epochs = request.epochs
    batch_size = request.batch_size
    seq_len = request.seq_len
    learning_rate = request.learning_rate
    seed = request.seed

    # P2 超参元学习：auto_params=True 时从高命中率模型采样参数
    if request.auto_params:
        recommended = await asyncio.to_thread(
            sample_recommended_params, lottery_type)
        if recommended:
            epochs = recommended["epochs"]
            batch_size = recommended["batch_size"]
            learning_rate = recommended["learning_rate"]

    if request.with_fetch:
        task = run_full_pipeline.delay(
            lottery_type=lottery_type,
            epochs=epochs,
            batch_size=batch_size,
            seq_len=seq_len,
            learning_rate=learning_rate,
            seed=seed
        )
        message = "完整训练任务已提交（先抓取数据再训练）"
    else:
        task = start_training.delay(
            lottery_type=lottery_type,
            epochs=epochs,
            batch_size=batch_size,
            seq_len=seq_len,
            learning_rate=learning_rate,
            seed=seed
        )
        message = "训练任务已提交"

    if request.auto_params:
        message += f"（自动参数: epochs={epochs}, bs={batch_size}, lr={learning_rate:.8f}）"

    return TrainResponse(
        task_id=task.id,
        status="pending",
        message=message
    )

@router.get("/status/{task_id}")
async def get_train_status(task_id: str):
    """
    查询训练任务状态。
    返回状态信息（pending/running/completed/failed）及结果。
    """
    task = AsyncResult(task_id, app=celery_app)
    if task.state == 'PENDING':
        return {"task_id": task_id, "status": "pending", "result": None}
    elif task.state == 'RUNNING':
        return {"task_id": task_id, "status": "running", "result": task.info}
    elif task.state == 'SUCCESS':
        return {"task_id": task_id, "status": "completed", "result": task.result}
    elif task.state == 'FAILURE':
        return {"task_id": task_id, "status": "failed", "result": str(task.info)}
    else:
        return {"task_id": task_id, "status": task.state, "result": None}