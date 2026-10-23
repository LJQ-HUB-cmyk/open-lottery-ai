# -*- coding: utf-8 -*-
"""
集成预测服务：按回测命中率加权融合 Top-K 模型的概率分布，生成共识号码。

自我学习闭环的决策层：
- 模型权重 = 回测综合命中率（自我学习反馈）
- 概率融合 = sigmoid 概率加权平均（消除单模型噪声）
- 选号确定性 Top-K（集成结果稳定可复现）
"""
import asyncio
import os
from datetime import date

import numpy as np
import torch
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.model_score import ModelScore
from app.services.analysis_service import get_next_draw_date, is_draw_day
from .data_loader import (
    load_ssq_data, load_dlt_data,
    SSQ_FEATURE_COLS, SSQ_TARGET_COLS,
    DLT_FEATURE_COLS, DLT_TARGET_COLS,
    SSQ_RED_RANGE, SSQ_BLUE_RANGE,
    DLT_FRONT_RANGE, DLT_BACK_RANGE,
)
from .backtest_service import _load_lottery_config
# 复用 predictor 的模型/标准化器/meta 缓存与批量入库，避免重复实现
from .predictor import (
    _load_meta, _load_model_cached, _load_scaler_cached, _bulk_upsert_forecasts,
)


def _topk_deterministic(probs: np.ndarray, k: int) -> list:
    """
    概率 Top-K 确定性选号（1-based）。
    """
    idx = np.argsort(-probs)[:k]
    return sorted(int(i) + 1 for i in idx)


def _member_probs_sync(model_file, save_dir, lottery_type, df,
                       feature_dim, target_cols, num_red, num_blue):
    """
    加载单个成员模型并推理，返回 sigmoid 概率数组；文件缺失/旧模型返回 None。
    同步 CPU 密集逻辑，供 asyncio.to_thread 在线程池并行调用。
    """
    run_id = os.path.splitext(model_file)[0]
    model_path = os.path.join(save_dir, model_file)
    meta_path = os.path.join(save_dir, f"{run_id}_meta.json")
    scaler_path = os.path.join(save_dir, f"{run_id}_scaler.joblib")
    if not (os.path.exists(model_path) and os.path.exists(meta_path) and os.path.exists(scaler_path)):
        return None

    meta = _load_meta(save_dir, lottery_type, model_file)
    if meta.get("model_type") != "classifier":
        return None

    seq_len = int(meta.get("pred_seq_len", 30))
    if seq_len >= len(df):
        return None

    last_seq = df.values[-seq_len:]
    scaler = _load_scaler_cached(scaler_path)
    feats = scaler.transform(last_seq[:, :feature_dim].astype(np.float32))
    seq = np.concatenate([feats, last_seq[:, feature_dim:].astype(np.float32)], axis=1)
    x = torch.tensor(seq, dtype=torch.float32).unsqueeze(0)

    model = _load_model_cached(
        model_path, meta, num_red, num_blue,
        feature_dim + len(target_cols))
    with torch.no_grad():
        logits = model(x).float().squeeze().numpy()
    return 1.0 / (1.0 + np.exp(-logits))


async def ensemble_predict(lottery_type: str, top_k: int = None):
    """
    加权融合回测最优 Top-K 模型，生成集成预测并存入 forecast 表。
    top_k 不传时取配置 ENSEMBLE_TOP_K。
    """
    top_k = top_k or settings.ENSEMBLE_TOP_K
    (load_fn, feature_cols, target_cols, num_red, num_blue,
     red_upper, blue_upper, red_pick, blue_pick) = _load_lottery_config(lottery_type)

    # ---- 1. 从 model_score 表取 Top-K（自我学习反馈） ----
    async with AsyncSessionLocal() as db:
        stmt = select(ModelScore).where(
            ModelScore.lottery_type == lottery_type,
        ).order_by(ModelScore.hit_total.desc()).limit(top_k)
        scores = (await db.execute(stmt)).scalars().all()
    if not scores:
        raise ValueError("暂无回测评分，请先执行回测（POST /predict/backtest）")

    base_dir = settings.MODEL_SAVE_DIR
    save_dir = os.path.join(base_dir, lottery_type)
    feature_dim = len(feature_cols)

    # ---- 2. 加载数据与输入窗口 ----
    df = await (load_ssq_data() if lottery_type == 'ssq' else load_dlt_data())
    members = []
    fused_red = np.zeros(num_red, dtype=np.float64)
    fused_blue = np.zeros(num_blue, dtype=np.float64)
    weight_sum = 0.0

    # ---- 2. 成员模型并行推理（线程池，复用 predictor 的模型缓存）----
    tasks = [
        asyncio.to_thread(
            _member_probs_sync, score.model_name, save_dir, lottery_type,
            df, feature_dim, target_cols, num_red, num_blue)
        for score in scores
    ]
    probs_list = await asyncio.gather(*tasks)

    for score, probs in zip(scores, probs_list):
        if probs is None:
            continue

        # 等权集成：避免 winner's curse（历史 hit_total 最高的模型本质是噪音最大的，
        # 越押权重在它身上，越容易向均值回归）
        w = 1.0
        fused_red[:num_red] += w * probs[:num_red]
        fused_blue[:num_blue] += w * probs[num_red:]
        weight_sum += w

        members.append({
            "model_name": score.model_name,
            "hit_total": round(float(score.hit_total), 4),
            "weight": round(w, 4),
        })

    if not members or weight_sum == 0:
        raise ValueError("Top-K 模型均无法加载，请重新回测或训练")

    fused_red /= weight_sum
    fused_blue /= weight_sum

    # ---- 3. 确定性 Top-K 选号 ----
    reds = _topk_deterministic(fused_red, red_pick)
    blues = _topk_deterministic(fused_blue, blue_pick)

    # 质量评分：融合概率 Top-K 均值
    top_red = np.sort(fused_red)[::-1][:red_pick]
    top_blue = np.sort(fused_blue)[::-1][:blue_pick]
    avg_prob = float(np.mean(top_red) * 0.7 + np.mean(top_blue) * 0.3)
    quality_score = round(float(np.clip(avg_prob, 0, 1) * 0.9 + 0.1), 3)

    # ---- 4. 计算目标开奖日期并入库 ----
    today = date.today()
    if is_draw_day(lottery_type, today):
        target_date = today
    else:
        target_date = get_next_draw_date(lottery_type, today)
        if target_date is None:
            raise ValueError(f"无法找到 {lottery_type} 的下一个开奖日")

    ensemble_name = f"ensemble_top{len(members)}"
    # 复用 predictor 的批量入库（单条），保证入库逻辑单一来源
    await _bulk_upsert_forecasts(
        lottery_type, target_date,
        [{"model_name": ensemble_name, "red": reds, "blue": blues,
          "quality_score": quality_score}])

    return {
        "lottery_type": lottery_type,
        "forecast_date": target_date.strftime("%Y-%m-%d"),
        "red": reds,
        "blue": blues,
        "quality_score": quality_score,
        "model_version": ensemble_name,
        "members": members,
    }
