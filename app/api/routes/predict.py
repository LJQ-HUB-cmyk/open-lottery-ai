# -*- coding: utf-8 -*-
"""
预测接口：基于已训练模型生成预测结果。
"""
import asyncio
import json
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.core.celery_app import celery_app
from app.schemas.lottery import PredictRequest, PredictResponse, TrainResponse, BatchPredictRequest
from app.services.predictor import (
    get_prediction, get_predictions_batch, iter_predictions_batch,
)
from app.services.backtest_service import get_leaderboard
from app.services.ensemble_service import ensemble_predict
from app.services.diagnostic_service import run_diagnostic, quick_diagnostic
from app.tasks.training_jobs import run_backtest

router = APIRouter(prefix="/predict", tags=["Prediction"])

@router.post("/", response_model=PredictResponse)
async def predict(request: PredictRequest):
    """
    根据彩种和模型版本生成预测号码。
    自动将预测结果保存到对应的 forecast 表中。
    """
    try:
        result = await get_prediction(
            lottery_type=request.lottery_type,
            model_version=request.model_version,
            model_name=request.model_name   # 新增传递
        )
        # 单模型预测同样写入复试方案（与批量/一键智能预测保持一致）
        from app.services.predictor import _auto_generate_fushi
        await _auto_generate_fushi(
            request.lottery_type, result.get("forecast_date", date.today())
        )
        return PredictResponse(
            lottery_type=request.lottery_type,
            forecast_date=result.get("forecast_date", date.today()),
            red=result["red"],
            blue=result["blue"],
            quality_score=result.get("quality_score"),
            model_version=result.get("model_version", "Transformer")
        )
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"预测失败: {str(e)}")


@router.post("/batch/{lottery_type}")
async def predict_batch(lottery_type: str, request: BatchPredictRequest):
    """
    批量并行预测：一次提交多个模型，后端线程池并行推理 + 批量入库。
    相比前端逐个请求，数据只加载一次、单会话提交、推理不阻塞事件循环。
    """
    if lottery_type not in ("ssq", "dlt"):
        raise HTTPException(400, "lottery_type 必须是 ssq 或 dlt")
    if not request.models:
        raise HTTPException(400, "models 不能为空")
    try:
        workers = min(max(request.max_workers or 16, 1), 16)
        return await get_predictions_batch(lottery_type, request.models, max_workers=workers)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"批量预测失败: {str(e)}")


@router.post("/batch-stream/{lottery_type}")
async def predict_batch_stream(lottery_type: str, request: BatchPredictRequest):
    """
    批量并行预测（流式）：NDJSON 响应，每行一个 JSON 事件，前端可逐行读取实时进度。
    事件类型：start（总数）→ progress（单模型完成）× N → done（汇总）；异常时推 error 事件。
    """
    if lottery_type not in ("ssq", "dlt"):
        raise HTTPException(400, "lottery_type 必须是 ssq 或 dlt")
    if not request.models:
        raise HTTPException(400, "models 不能为空")
    workers = min(max(request.max_workers or 16, 1), 16)

    async def event_generator():
        try:
            async for evt in iter_predictions_batch(lottery_type, request.models, max_workers=workers):
                yield json.dumps(evt, ensure_ascii=False) + "\n"
        except Exception as e:  # noqa: BLE001
            yield json.dumps({"type": "error",
                             "error": f"批量预测失败: {type(e).__name__}: {e}"},
                             ensure_ascii=False) + "\n"

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.post("/backtest/{lottery_type}", response_model=TrainResponse)
async def start_backtest(lottery_type: str, n_periods: int = 30):
    """
    提交回测任务：回测彩种下所有模型的真实命中率，写入 model_score 表。
    """
    if lottery_type not in ("ssq", "dlt"):
        raise HTTPException(400, "lottery_type 必须是 ssq 或 dlt")
    task = run_backtest.delay(lottery_type=lottery_type, n_periods=n_periods)
    return TrainResponse(task_id=task.id, status="pending", message="回测任务已提交")


@router.get("/leaderboard/{lottery_type}")
async def leaderboard(
    lottery_type: str,
    page: int = Query(1, ge=1, description="页码，从 1 开始"),
    page_size: int = Query(10, ge=1, le=100, description="每页条数（1~100）"),
):
    """
    获取模型真实命中率榜单（按回测综合命中率降序，服务端分页）。
    返回当前页数据 + total 总数；同步 DB 查询放线程池，不阻塞事件循环。
    """
    if lottery_type not in ("ssq", "dlt"):
        raise HTTPException(400, "lottery_type 必须是 ssq 或 dlt")
    result = await asyncio.to_thread(get_leaderboard, lottery_type, page, page_size)
    result["lottery_type"] = lottery_type
    return result


@router.post("/ensemble/{lottery_type}")
async def ensemble(lottery_type: str, top_k: int = 5):
    """
    集成预测：按回测命中率加权融合 Top-K 模型，生成共识号码。
    """
    if lottery_type not in ("ssq", "dlt"):
        raise HTTPException(400, "lottery_type 必须是 ssq 或 dlt")
    try:
        return await ensemble_predict(lottery_type, top_k=top_k)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"集成预测失败: {str(e)}")


@router.get("/diagnostic/{lottery_type}")
def diagnostic(lottery_type: str, n_periods: int = Query(default=None, ge=10),
               top_k: int = Query(default=5, ge=1), z: float = Query(default=1.96)):
    """
    双向一致性诊断：随机基线 + 严格样本外回测 + 正向/反向一致性判定。

    返回内容包含：
    - 随机基线（解析法 + 95% 阈值 + 2 万次蒙特卡洛交叉验证）
    - forward / backward 各 Top-K 模型的 lift + 95% CI
    - 双向一致性判定结论（SIGNAL_DETECTED / NO_SIGNAL / INCONSISTENT）
    """
    if lottery_type not in ("ssq", "dlt"):
        raise HTTPException(400, "lottery_type 必须是 ssq 或 dlt")
    try:
        report = run_diagnostic(lottery_type, n_periods=n_periods, top_k=top_k, z=z)
    except Exception as e:
        raise HTTPException(500, f"诊断失败: {e}")
    return report