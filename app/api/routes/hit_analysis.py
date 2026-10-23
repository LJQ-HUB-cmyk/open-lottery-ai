# -*- coding: utf-8 -*-
"""
数据分析（命中分析）API 路由。
选择历史开奖期，与对标期的预测记录逐条对比命中，按命中数降序排序。
"""
from fastapi import APIRouter, HTTPException, Query

from app.services.hit_analysis_service import (
    get_analyzable_draws,
    analyze_draw_hits,
    get_model_training_params,
    aggregate_hit_analysis,
)

router = APIRouter(prefix="/hit-analysis", tags=["HitAnalysis"])


@router.get("/draws")
async def list_analyzable_draws(
    lottery_type: str = Query('ssq', description="彩种：ssq 或 dlt"),
    limit: int = Query(100, ge=1, le=500, description="取最近 N 期开奖")
):
    """
    获取可做命中分析的历史开奖期列表（必须存在对标预测记录）。
    """
    if lottery_type not in ('ssq', 'dlt'):
        raise HTTPException(status_code=400, detail="lottery_type 必须是 ssq 或 dlt")
    try:
        draws = await get_analyzable_draws(lottery_type, limit)
        return {"lottery_type": lottery_type, "total": len(draws), "items": draws}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询可分析期数失败: {str(e)}")


@router.get("/detail")
async def get_hit_detail(
    lottery_type: str = Query('ssq', description="彩种：ssq 或 dlt"),
    issue_num: str = Query(None, description="开奖期号"),
    draw_date: str = Query(None, description="开奖日期 YYYY-MM-DD（期号优先）")
):
    """
    获取指定开奖期的预测命中分析明细（按命中总数降序，全部预测参与统计）。
    """
    if lottery_type not in ('ssq', 'dlt'):
        raise HTTPException(status_code=400, detail="lottery_type 必须是 ssq 或 dlt")
    if not issue_num and not draw_date:
        raise HTTPException(status_code=400, detail="必须提供 issue_num 或 draw_date")
    try:
        return await analyze_draw_hits(lottery_type, issue_num=issue_num, draw_date=draw_date)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"命中分析失败: {str(e)}")


@router.get("/model-params")
async def get_model_params(
    lottery_type: str = Query('ssq', description="彩种：ssq 或 dlt"),
    model_version: str = Query(..., description="模型版本（.pt 文件名）")
):
    """
    获取指定模型的训练参数（从 _meta.json 读取）。
    用于在命中分析中查看某个模型是用什么参数训练的。
    """
    if lottery_type not in ('ssq', 'dlt'):
        raise HTTPException(status_code=400, detail="lottery_type 必须是 ssq 或 dlt")
    params = get_model_training_params(lottery_type, model_version)
    if not params:
        raise HTTPException(status_code=404, detail=f"未找到模型 {model_version} 的元信息")
    return {"lottery_type": lottery_type, "model_version": model_version, "training_params": params}


@router.get("/aggregate")
async def get_aggregate_analysis(
    lottery_type: str = Query('ssq', description="彩种：ssq 或 dlt"),
    recent_n: int = Query(10, ge=1, le=50, description="聚合最近 N 期开奖")
):
    """
    聚合最近 N 期的命中分析，按模型汇总平均命中率、中奖率与训练参数。
    用于在数据分析页展示哪些模型/参数组合持续表现优异。
    """
    if lottery_type not in ('ssq', 'dlt'):
        raise HTTPException(status_code=400, detail="lottery_type 必须是 ssq 或 dlt")
    try:
        return await aggregate_hit_analysis(lottery_type, recent_n=recent_n)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"聚合分析失败: {str(e)}")
