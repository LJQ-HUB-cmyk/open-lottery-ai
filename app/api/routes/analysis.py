# -*- coding: utf-8 -*-
"""
预测分析 + 复试分析 API 路由。
业务逻辑在 analysis_service / fushi_service，路由仅做参数校验与异常包装。
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.analysis_service import get_today_analysis_payload
from app.services.fushi_service import (
    generate_fushi, list_fushi, evaluate_fushi_history,
)

router = APIRouter(prefix="/analysis", tags=["Analysis"])


@router.get("/today")
async def get_today_analysis(lottery_type: str = Query('ssq', description="彩种：ssq或dlt")):
    """
    获取当前开奖期的预测分析结果：预测记录（全部保留，相似度仅标记）、
    最优推荐号码、开奖结果、号码频率统计、全组合表 ID（未导入全组合时为空）。
    """
    if lottery_type not in ('ssq', 'dlt'):
        raise HTTPException(400, "lottery_type 必须是 ssq 或 dlt")
    try:
        return await get_today_analysis_payload(lottery_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")


# ============ 复试分析 ============

class FushiGenerateRequest(BaseModel):
    lottery_type: str = Field(..., description="ssq 或 dlt")
    forecast_date: Optional[str] = Field(None, description="指定日期 YYYY-MM-DD，不传取当前目标开奖日")


@router.post("/fushi/generate")
async def post_fushi_generate(req: FushiGenerateRequest):
    """
    根据当期预测号码频率，生成 7+1 / 7+2 / 8+1 / 8+2 四档复试方案并入库。
    """
    if req.lottery_type not in ('ssq', 'dlt'):
        raise HTTPException(400, "lottery_type 必须是 ssq 或 dlt")
    try:
        target = date.fromisoformat(req.forecast_date) if req.forecast_date else None
        result = await generate_fushi(req.lottery_type, target)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"复试生成失败: {str(e)}")


@router.get("/fushi/list")
async def get_fushi_list(
    lottery_type: str = Query(..., description="ssq 或 dlt"),
    forecast_date: Optional[str] = Query(None, description="指定日期，不传返回最新 N 期"),
    limit: int = Query(default=20, ge=1, le=100),
):
    """
    查询已生成的复试方案（含全部注展开 combo_detail）。
    forecast_date 不传 → 返回最新 N 期。
    """
    if lottery_type not in ('ssq', 'dlt'):
        raise HTTPException(400, "lottery_type 必须是 ssq 或 dlt")
    try:
        target = date.fromisoformat(forecast_date) if forecast_date else None
        rows = await list_fushi(lottery_type, target, limit=limit)
        return {"items": rows, "total": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询复试失败: {str(e)}")


class FushiEvaluateRequest(BaseModel):
    lottery_type: str = Field(..., description="ssq 或 dlt")
    issue_num: Optional[int] = Field(None, description="开奖期号（二选一）")
    forecast_date: Optional[str] = Field(None, description="开奖日期 YYYY-MM-DD（二选一）")


@router.post("/fushi/evaluate")
async def post_fushi_evaluate(req: FushiEvaluateRequest):
    """
    对某期已开奖的复试方案，计算历史命中评估（每注中多少，最高奖级）并回填 hit_analysis 表。
    """
    if req.lottery_type not in ('ssq', 'dlt'):
        raise HTTPException(400, "lottery_type 必须是 ssq 或 dlt")
    if req.issue_num is None and not req.forecast_date:
        raise HTTPException(400, "issue_num 和 forecast_date 必须至少传一个")
    try:
        key = req.issue_num if req.issue_num is not None else req.forecast_date
        result = await evaluate_fushi_history(req.lottery_type, key)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"历史评估失败: {str(e)}")
