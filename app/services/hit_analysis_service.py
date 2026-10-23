# -*- coding: utf-8 -*-
"""
命中分析服务：选择历史开奖期，与对标期（forecast_date = 开奖日）的预测记录逐条对比。
- 按双色球 / 大乐透官方中奖规则判定奖级
- 按命中总数降序排序（7中 → 0中）
相似度剔除功能已下线，全部预测参与统计，不再区分保留/剔除。
"""
from sqlalchemy import select, desc, func

from app.core.database import AsyncSessionLocal
from app.models.dlt_forecast import DLTForecast
from app.models.dlt_history import DLTHistory
from app.models.hit_analysis import HitAnalysis
from app.models.ssq_forecast import SSQForecast
from app.models.ssq_history import SSQHistory
from app.services.fushi_service import evaluate_fushi_history
from app.services.number_utils import extract_history_numbers, extract_forecast_numbers

# ==================== 中奖规则配置 ====================
# 奖级判定表：(红球命中数, 蓝球命中数) -> 奖级名称
SSQ_PRIZE_RULES = {
    (6, 1): "一等奖",
    (6, 0): "二等奖",
    (5, 1): "三等奖",
    (5, 0): "四等奖",
    (4, 1): "四等奖",
    (4, 0): "五等奖",
    (3, 1): "五等奖",
    (2, 1): "六等奖",
    (1, 1): "六等奖",
    (0, 1): "六等奖",
}

DLT_PRIZE_RULES = {
    (5, 2): "一等奖",
    (5, 1): "二等奖",
    (5, 0): "三等奖",
    (4, 2): "四等奖",
    (4, 1): "五等奖",
    (3, 2): "六等奖",
    (4, 0): "七等奖",
    (3, 1): "八等奖",
    (2, 2): "八等奖",
    (3, 0): "九等奖",
    (2, 1): "九等奖",
    (1, 2): "九等奖",
    (0, 2): "九等奖",
}

# 奖级展示顺序（用于汇总统计）
PRIZE_ORDER = ["一等奖", "二等奖", "三等奖", "四等奖", "五等奖",
               "六等奖", "七等奖", "八等奖", "九等奖", "未中奖"]


def _get_models(lottery_type):
    """
    返回彩种对应的 (历史开奖模型, 预测记录模型)。
    """
    if lottery_type == 'ssq':
        return SSQHistory, SSQForecast
    return DLTHistory, DLTForecast


def _judge_prize(lottery_type, red_hits, blue_hits):
    """
    按官方规则判定奖级，未中奖返回 "未中奖"。
    """
    rules = SSQ_PRIZE_RULES if lottery_type == 'ssq' else DLT_PRIZE_RULES
    return rules.get((red_hits, blue_hits), "未中奖")


async def get_analyzable_draws(lottery_type='ssq', limit=100):
    """
    返回最近有对标预测记录的历史开奖期列表（按期号降序），供前端下拉选择。
    每条包含期号、开奖日期、预测条数。
    """
    hist_model, fc_model = _get_models(lottery_type)

    async with AsyncSessionLocal() as db:
        hist_rows = (await db.execute(
            select(hist_model).order_by(desc(hist_model.issue_num)).limit(limit)
        )).scalars().all()

        # 统计这些开奖日期上的预测条数
        date_to_row = {h.draw_date: h for h in hist_rows}
        counts = {}
        if date_to_row:
            rows = (await db.execute(
                select(fc_model.forecast_date, func.count(fc_model.id))
                .where(fc_model.forecast_date.in_(list(date_to_row.keys())))
                .group_by(fc_model.forecast_date)
            )).all()
            counts = {r[0]: r[1] for r in rows}

        result = []
        for h in hist_rows:
            cnt = counts.get(h.draw_date, 0)
            if cnt > 0:
                reds, blues = extract_history_numbers(lottery_type, h)
                result.append({
                    "issue_num": h.issue_num,
                    "draw_date": h.draw_date.strftime("%Y-%m-%d") if h.draw_date else None,
                    "forecast_count": cnt,
                    "red": reds,
                    "blue": blues
                })
        return result


async def analyze_draw_hits(lottery_type='ssq', issue_num=None, draw_date=None):
    """
    对指定开奖期的全部预测做命中分析。
    指定方式：issue_num 优先，否则按 draw_date（YYYY-MM-DD）匹配。
    返回开奖信息 + 按命中数降序的明细列表 + 命中分布 / 奖级汇总。
    """
    if not issue_num and not draw_date:
        raise ValueError("必须提供 issue_num 或 draw_date")

    hist_model, fc_model = _get_models(lottery_type)

    async with AsyncSessionLocal() as db:
        # 1. 定位开奖记录
        stmt = select(hist_model)
        if issue_num:
            stmt = stmt.where(hist_model.issue_num == str(issue_num))
        else:
            stmt = stmt.where(hist_model.draw_date == draw_date)
        hist = (await db.execute(
            stmt.order_by(desc(hist_model.issue_num)).limit(1)
        )).scalar_one_or_none()
        if hist is None:
            raise LookupError(f"未找到开奖记录：{issue_num or draw_date}")

        # 2. 取对标期（forecast_date = 开奖日）的全部预测
        forecasts = (await db.execute(
            select(fc_model).where(fc_model.forecast_date == hist.draw_date)
        )).scalars().all()

    draw_reds, draw_blues = extract_history_numbers(lottery_type, hist)

    # 3. 逐条计算命中
    items = []
    for f in forecasts:
        f_reds, f_blues = extract_forecast_numbers(lottery_type, f)
        hit_red_numbers = sorted(set(f_reds) & set(draw_reds))
        hit_blue_numbers = sorted(set(f_blues) & set(draw_blues))
        red_hits = len(hit_red_numbers)
        blue_hits = len(hit_blue_numbers)
        prize = _judge_prize(lottery_type, red_hits, blue_hits)
        items.append({
            "model_version": f.model_version,
            "quality_score": f.quality_score,
            "create_time": f.create_time.strftime("%Y-%m-%d %H:%M:%S") if f.create_time else None,
            "red": f_reds,
            "blue": f_blues,
            "hit_red_numbers": hit_red_numbers,
            "hit_blue_numbers": hit_blue_numbers,
            "red_hits": red_hits,
            "blue_hits": blue_hits,
            "total_hits": red_hits + blue_hits,
            "prize": prize
        })

    # 4. 排序：总命中 ↓ → 红球命中 ↓ → 蓝球命中 ↓ → 质量评分 ↓
    items.sort(key=lambda x: (
        -x["total_hits"], -x["red_hits"], -x["blue_hits"], -(x["quality_score"] or 0)
    ))

    # 5. 命中分布汇总（全部预测，不再区分保留/剔除）
    max_total = len(draw_reds) + len(draw_blues)
    hit_distribution = []
    for total in range(max_total, -1, -1):
        count = sum(1 for x in items if x["total_hits"] == total)
        hit_distribution.append({"total_hits": total, "count": count})

    # 6. 奖级汇总
    prize_summary = []
    for prize in PRIZE_ORDER:
        count = sum(1 for x in items if x["prize"] == prize)
        if count:
            prize_summary.append({"prize": prize, "count": count})

    # 7. 复试方案历史命中（自动从 hit_analysis 表取；已开奖则自动评估）
    fushi_plans = []
    try:
        fushi_plans = await _fetch_fushi_hit_plans(lottery_type, hist.draw_date)
    except Exception:
        fushi_plans = []

    return {
        "lottery_type": lottery_type,
        "draw": {
            "issue_num": hist.issue_num,
            "draw_date": hist.draw_date.strftime("%Y-%m-%d") if hist.draw_date else None,
            "red": draw_reds,
            "blue": draw_blues
        },
        "total_forecasts": len(items),
        "win_count": sum(1 for x in items if x["prize"] != "未中奖"),
        "hit_distribution": hit_distribution,
        "prize_summary": prize_summary,
        "items": items,
        # ===== 复试方案命中 =====
        "fushi_plans": fushi_plans,
        "fushi_present": len(fushi_plans) > 0,
    }


async def _fetch_fushi_hit_plans(lottery_type: str, forecast_date) -> list:
    """
    查询指定开奖期对应的复试方案命中数据（只读展示）。
    - 不在此处生成复试：复试的写入统一由 analysis 页对应链路（预测完成时）负责
    - 该期无复试记录 → 直接返回空，页面不展示该卡片
    - 已存在但未评估 → 回填命中与奖金
    """
    from datetime import date as _date_type
    target = forecast_date if isinstance(forecast_date, _date_type) else \
        _date_type.fromisoformat(str(forecast_date))

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(HitAnalysis).where(
                HitAnalysis.lottery_type == lottery_type,
                HitAnalysis.forecast_date == target,
            ).order_by(HitAnalysis.pattern)
        )).scalars().all()

    if not rows:
        return []

    # 检查是否需要评估（未评估过，或历史数据缺少新的中奖金额字段 → 整期重算）
    need_eval = any(
        ((not r.is_history_hit) and r.prize_level is None) or r.prize_detail is None
        for r in rows
    )
    if need_eval:
        await evaluate_fushi_history(lottery_type, target)
        # 评估完重新读一次
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(HitAnalysis).where(
                    HitAnalysis.lottery_type == lottery_type,
                    HitAnalysis.forecast_date == target,
                ).order_by(HitAnalysis.pattern)
            )).scalars().all()

    result = []
    for r in rows:
        result.append({
            "pattern": r.pattern,
            "red_pool": r.red_pool,
            "blue_pool": r.blue_pool,
            "bet_count": r.bet_count,
            "bet_amount": r.bet_amount,
            "is_history_hit": bool(r.is_history_hit),
            "prize_level": r.prize_level or "未中奖",
            "prize_amount": r.prize_amount or 0,
            "prize_detail": r.prize_detail or {},
            "float_prize_count": r.float_prize_count or 0,
            "profit": (r.prize_amount or 0) - (r.bet_amount or 0),
            "hit_reds": r.hit_reds or {},
            "hit_blues": r.hit_blues or {},
            "freq_support": r.freq_support,
            "quality_avg": r.quality_avg,
        })
    return result


def get_model_training_params(lottery_type: str, model_version: str) -> dict:
    """
    从模型 _meta.json 读取训练参数，供命中分析展示模型来源参数。
    model_version: 预测记录的 model_version 字段（即 .pt 文件名）。
    无 meta 文件时返回空 dict。
    """
    import json
    import os
    from app.core.config import settings

    model_dir = os.path.join(settings.MODEL_SAVE_DIR, lottery_type)

    if model_version.endswith('_final.pt'):
        meta_path = os.path.join(model_dir, f"{lottery_type}_final_meta.json")
    else:
        run_id = os.path.splitext(model_version)[0]
        meta_path = os.path.join(model_dir, f"{run_id}_meta.json")

    if not os.path.exists(meta_path):
        return {}

    try:
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
    except Exception:
        return {}

    return {
        "epochs": meta.get("epochs"),
        "batch_size": meta.get("batch_size"),
        "seq_len": meta.get("seq_len"),
        "learning_rate": meta.get("learning_rate"),
        "seed": meta.get("seed"),
        "d_model": meta.get("d_model"),
        "nhead": meta.get("nhead"),
        "num_layers": meta.get("num_layers"),
        "dropout": meta.get("dropout"),
        "best_epoch": meta.get("best_epoch"),
        "best_hit_rate": meta.get("best_hit_rate"),
        "final_hit_rate": meta.get("final_hit_rate"),
        "trained_at": meta.get("trained_at"),
    }


async def aggregate_hit_analysis(lottery_type='ssq', recent_n=10) -> dict:
    """
    聚合最近 N 期的命中分析，按模型汇总平均命中率与奖级分布。
    每个模型附带训练参数（从 _meta.json 读取）。
    复用 get_analyzable_draws + analyze_draw_hits，不重复命中计算逻辑。
    """
    draws = await get_analyzable_draws(lottery_type, limit=recent_n)
    if not draws:
        return {
            "lottery_type": lottery_type,
            "periods_analyzed": 0,
            "total_models": 0,
            "models": []
        }

    model_stats = {}  # {model_version: stats_dict}

    for draw in draws:
        try:
            detail = await analyze_draw_hits(
                lottery_type, issue_num=draw["issue_num"])
        except Exception:
            continue

        for item in detail["items"]:
            mv = item["model_version"]
            if mv not in model_stats:
                model_stats[mv] = {
                    "model_version": mv,
                    "red_hits_sum": 0,
                    "blue_hits_sum": 0,
                    "total_hits_sum": 0,
                    "period_count": 0,
                    "win_count": 0,
                    "prizes": {},
                }
            s = model_stats[mv]
            s["red_hits_sum"] += item["red_hits"]
            s["blue_hits_sum"] += item["blue_hits"]
            s["total_hits_sum"] += item["total_hits"]
            s["period_count"] += 1
            if item["prize"] != "未中奖":
                s["win_count"] += 1
            s["prizes"][item["prize"]] = \
                s["prizes"].get(item["prize"], 0) + 1

    models = []
    for mv, s in model_stats.items():
        n = s["period_count"]
        params = get_model_training_params(lottery_type, mv)
        models.append({
            "model_version": mv,
            "period_count": n,
            "avg_red_hits": round(s["red_hits_sum"] / n, 4),
            "avg_blue_hits": round(s["blue_hits_sum"] / n, 4),
            "avg_total_hits": round(s["total_hits_sum"] / n, 4),
            "win_count": s["win_count"],
            "win_rate": round(s["win_count"] / n, 4),
            "prizes": s["prizes"],
            "training_params": params,
        })

    models.sort(key=lambda x: -x["avg_total_hits"])

    return {
        "lottery_type": lottery_type,
        "periods_analyzed": len(draws),
        "total_models": len(models),
        "models": models,
    }
