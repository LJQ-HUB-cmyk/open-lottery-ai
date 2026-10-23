# -*- coding: utf-8 -*-
"""
模型管理接口：列出已训练模型、下载模型文件。

模型保存时文件名末尾带训练 Unix 时间戳（trainer.py 生成 run_id），
本期过滤即基于该时间戳：只返回最近一期已开奖之后训练的模型，
旧期模型（训练数据缺少最近开奖）不再返回给预测页。
"""
import glob
import os
from datetime import datetime, time as dtime, timedelta

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.dlt_history import DLTHistory
from app.models.ssq_history import SSQHistory
from app.services.analysis_service import get_target_draw_date

router = APIRouter(prefix="/models", tags=["Models"])


def _train_ts_of(filename: str):
    """
    从模型文件名末尾提取训练 Unix 时间戳（如 ssq_epochs50_bs64_seq100_lr0_00005_1757300000.pt → 1757300000）。
    解析失败返回 None（早期/异常命名的文件）。
    """
    base = os.path.basename(filename)
    if not base.endswith('.pt'):
        return None
    tail = base[:-3].rsplit('_', 1)[-1]
    try:
        return int(tail)
    except ValueError:
        return None


async def _get_last_draw_date(lottery_type: str):
    """查询历史表中最近一期已开奖日期（本期时间窗的起点）"""
    model = SSQHistory if lottery_type == 'ssq' else DLTHistory
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(func.max(model.draw_date)))).scalar()


@router.get("/list")
async def list_models(
    lottery_type: str = Query(None, description="彩种 ssq/dlt，配合 current_period 使用"),
    current_period: bool = Query(False, description="仅返回本期（最近一期开奖后训练）的模型"),
):
    """
    列出已保存的模型文件。
    - 不带参数：兼容旧调用（仪表盘），返回 ssq/dlt 全部 .pt + scaler 文件。
    - lottery_type + current_period=true：预测页专用，只返回本期模型——
      文件名训练时间戳 >= 最近一期已开奖日 00:00 的 .pt（不含 _final 与 scaler）。
    """
    base_dir = settings.MODEL_SAVE_DIR

    if not current_period or lottery_type not in ('ssq', 'dlt'):
        # ---------- 旧行为：返回全部文件 ----------
        if not os.path.exists(base_dir):
            return {"models": []}
        all_models = []
        for lt in ['ssq', 'dlt']:
            sub_dir = os.path.join(base_dir, lt)
            if os.path.exists(sub_dir):
                pt_files = glob.glob(os.path.join(sub_dir, "*.pt"))
                scaler_files = glob.glob(os.path.join(sub_dir, "*_scaler.joblib"))
                for f in pt_files + scaler_files:
                    all_models.append(os.path.basename(f))
        return {"models": sorted(all_models)}

    # ---------- 本期过滤模式（预测页） ----------
    sub_dir = os.path.join(base_dir, lottery_type)
    last_draw = await _get_last_draw_date(lottery_type)
    target_draw = get_target_draw_date(lottery_type)

    period_info = {
        "lottery_type": lottery_type,
        "last_draw_date": last_draw.strftime("%Y-%m-%d") if last_draw else None,
        "target_draw_date": target_draw.strftime("%Y-%m-%d") if target_draw else None,
        "total_all": 0,
        "total": 0,
    }
    if not os.path.exists(sub_dir):
        return {"models": [], "period": period_info}

    pt_files = glob.glob(os.path.join(sub_dir, "*.pt"))
    models = []
    if last_draw is not None:
        # 时间窗起点 = 最近一期开奖日 + 1 天 00:00
        # 理由：开奖日白天训练的模型，开奖号码尚未出来，用的仍是上一期数据，不算"本期"。
        #       开奖日晚上（开奖号出来后）训练的模型，其训练时间戳一定在次日 00:00 之后。
        period_start_date = last_draw + timedelta(days=1)
        period_start_ts = int(datetime.combine(period_start_date, dtime.min).timestamp())
        for f in pt_files:
            name = os.path.basename(f)
            if name.endswith('_final.pt'):
                continue
            period_info["total_all"] += 1
            ts = _train_ts_of(name)
            if ts is None:
                continue  # 无时间戳的文件无法判定是否本期，本期模式不返回
            if ts >= period_start_ts:
                models.append(name)
    else:
        # 历史表为空无法界定本期，退回全部普通模型
        for f in pt_files:
            name = os.path.basename(f)
            if not name.endswith('_final.pt'):
                models.append(name)
        period_info["total_all"] = len(models)

    period_info["total"] = len(models)
    return {"models": sorted(models), "period": period_info}


@router.get("/download/{model_name}")
async def download_model(model_name: str):
    """下载指定的模型文件，自动搜索 ssq 和 dlt 子目录"""
    # 防止路径遍历攻击
    if ".." in model_name or "/" in model_name or "\\" in model_name:
        raise HTTPException(400, "Invalid file name")

    base_dir = settings.MODEL_SAVE_DIR
    # 尝试在 ssq 和 dlt 子目录中查找
    for lottery_type in ['ssq', 'dlt']:
        sub_dir = os.path.join(base_dir, lottery_type)
        model_path = os.path.join(sub_dir, model_name)
        if os.path.exists(model_path):
            return FileResponse(model_path, filename=model_name)

    raise HTTPException(404, "Model not found")
