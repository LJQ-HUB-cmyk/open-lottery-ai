# -*- coding: utf-8 -*-
"""
复试分析服务：从预测号码频率池生成 7+1 / 7+2 / 8+1 / 8+2 四档复试方案，
展开全部组合注并写入 hit_analysis 表。

业务含义：
  双色球：红球池 N 选 6（投注），蓝球池 M 选 1（投注）
    7+1 = C(7,6)×C(1,1) = 7 注
    7+2 = C(7,6)×C(2,1) = 14 注
    8+1 = C(8,6)×C(1,1) = 28 注
    8+2 = C(8,6)×C(2,1) = 56 注
  大乐透：前区池 N 选 5，后区池 M 选 2（规则相同）

号码池来源：
  当期所有预测的号码频率统计 → 可按 quality_score 加权 → Top-8 红 + Top-2 蓝。
  如果某类号码预测数不够，会补随机号码（保底逻辑）。
"""
import asyncio
import logging
import random
from collections import Counter
from datetime import date
from itertools import combinations
from typing import Dict, List, Optional

from sqlalchemy import select, desc

from app.core.database import AsyncSessionLocal
from app.models.hit_analysis import HitAnalysis
from app.models.ssq_forecast import SSQForecast
from app.models.dlt_forecast import DLTForecast
from app.models.ssq_history import SSQHistory
from app.models.dlt_history import DLTHistory
from app.services.analysis_service import get_target_draw_date, LOTTERY_RULES
from app.services.number_utils import extract_forecast_numbers, extract_history_numbers

logger = logging.getLogger(__name__)

# ============ 复试档位矩阵 ============
# 每个档位 = (红球池大小, 蓝球池大小, pattern_str)
# 金额上限：单档 MAX_BET_COUNT_PER_PATTERN 注（None=不限制）
MAX_BET_COUNT_PER_PATTERN = None

# 双色球：pick_red=6, pick_blue=1
# 号码池上限：max_red_pool=12, max_blue_pool=4
# 最大档位 12+4 → C(12,6)×C(4,1)=924×4=3696 注 ¥7392
SSQ_PATTERNS = [
    (7, 1, "7+1"), (7, 2, "7+2"), (7, 3, "7+3"), (7, 4, "7+4"),
    (8, 1, "8+1"), (8, 2, "8+2"), (8, 3, "8+3"), (8, 4, "8+4"),
    (9, 1, "9+1"), (9, 2, "9+2"), (9, 3, "9+3"), (9, 4, "9+4"),
    (10, 1, "10+1"), (10, 2, "10+2"), (10, 3, "10+3"), (10, 4, "10+4"),
    (11, 1, "11+1"), (11, 2, "11+2"), (11, 3, "11+3"), (11, 4, "11+4"),
    (12, 1, "12+1"), (12, 2, "12+2"), (12, 3, "12+3"), (12, 4, "12+4"),
]

# 大乐透：pick_red=5, pick_blue=2
# 号码池上限：max_red_pool=11, max_blue_pool=4
# 最大档位 11+4 → C(11,5)×C(4,2)=462×6=2772 注 ¥5544
DLT_PATTERNS = [
    (6, 2, "6+2"), (6, 3, "6+3"), (6, 4, "6+4"),
    (7, 2, "7+2"), (7, 3, "7+3"), (7, 4, "7+4"),
    (8, 2, "8+2"), (8, 3, "8+3"), (8, 4, "8+4"),
    (9, 2, "9+2"), (9, 3, "9+3"), (9, 4, "9+4"),
    (10, 2, "10+2"), (10, 3, "10+3"), (10, 4, "10+4"),
    (11, 2, "11+2"), (11, 3, "11+3"), (11, 4, "11+4"),
]

PATTERNS_BY_LOTTERY = {
    "ssq": SSQ_PATTERNS,
    "dlt": DLT_PATTERNS,
}

# 彩种规则映射
LOTTERY_CONFIG = {
    "ssq": {
        "forecast_model": SSQForecast,
        "history_model": SSQHistory,
        "pick_red": 6,
        "pick_blue": 1,
        "red_max": 33,
        "blue_max": 16,
        "ball_unit": 2,
        "max_red_pool": 12,   # 号码池 Top-12
        "max_blue_pool": 4,   # 蓝球池 Top-4
    },
    "dlt": {
        "forecast_model": DLTForecast,
        "history_model": DLTHistory,
        "pick_red": 5,
        "pick_blue": 2,
        "red_max": 35,
        "blue_max": 12,
        "ball_unit": 2,
        "max_red_pool": 11,
        "max_blue_pool": 4,
    },
}


# ============ 频率分数表（GA 搜索空间） ============

async def _compute_freq_scores(
    lottery_type: str,
    target_date: date,
    use_quality_weight: bool = True,
) -> Optional[dict]:
    """
    计算某开奖期所有预测号码的频率分数（归一化到 [0, 1]）。
    返回全号码分表，不是 Top-N 切片——由 GA 在全量空间里优化。

    Returns:
        {"red_scores": {num: score}, "blue_scores": {num: score},
         "freq_support": int, "quality_avg": float}
        当期无预测 → None
    """
    cfg = LOTTERY_CONFIG[lottery_type]
    model = cfg["forecast_model"]

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(model).where(model.forecast_date == target_date)
        )).scalars().all()

    if not rows:
        return None

    red_counter = Counter()
    blue_counter = Counter()
    weighted_total = 0.0

    for row in rows:
        weight = row.quality_score or 0.5 if use_quality_weight else 1.0
        reds, blues = extract_forecast_numbers(lottery_type, row)
        for r in reds:
            red_counter[r] += weight
        for b in blues:
            blue_counter[b] += weight
        weighted_total += row.quality_score or 0.5

    # 归一化到 [0, 1]（除以 max 分）
    max_red = max(red_counter.values()) if red_counter else 1.0
    max_blue = max(blue_counter.values()) if blue_counter else 1.0
    red_scores = {n: c / max_red for n, c in red_counter.items()}
    blue_scores = {n: c / max_blue for n, c in blue_counter.items()}

    # 保证所有号码都有分（没被预测过的给 0.01，让 GA 有机会反向选）
    red_max_n = cfg["red_max"]
    blue_max_n = cfg["blue_max"]
    for n in range(1, red_max_n + 1):
        red_scores.setdefault(n, 0.01)
    for n in range(1, blue_max_n + 1):
        blue_scores.setdefault(n, 0.01)

    return {
        "red_scores": red_scores,
        "blue_scores": blue_scores,
        "freq_support": len(rows),
        "quality_avg": round(weighted_total / len(rows), 4),
    }


async def _load_recent_history_draws(
    lottery_type: str,
    n_periods: int = 30,
) -> List[Dict]:
    """
    加载最近 N 期历史开奖号（用于 GA 适应度里的回测项）。
    返回 [{"red": [...], "blue": [...]}, ...]，按时间倒序。
    """
    cfg = LOTTERY_CONFIG[lottery_type]
    history_model = cfg["history_model"]
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(history_model).order_by(history_model.draw_date.desc()).limit(n_periods)
        )).scalars().all()

    draws = []
    for row in rows:
        reds, blues = extract_history_numbers(lottery_type, row)
        if reds:
            draws.append({"red": sorted(reds), "blue": sorted(blues)})
    return draws


# ============ 号码池选取（保留用于兼容，但 generate_fushi 不再直接用） ============

async def _build_number_pool(
    lottery_type: str,
    target_date: date,
    top_red: int = 8,
    top_blue: int = 2,
    use_quality_weight: bool = True,
) -> Optional[dict]:
    """
    【兼容旧逻辑】基于频率分数取 Top-N 作为号码池。
    新的 generate_fushi 直接走 GA 优化，不再调用本函数。
    """
    score_data = await _compute_freq_scores(lottery_type, target_date, use_quality_weight)
    if score_data is None:
        return None
    cfg = LOTTERY_CONFIG[lottery_type]
    red_sorted = sorted(score_data["red_scores"].keys(),
                        key=lambda x: score_data["red_scores"][x], reverse=True)
    blue_sorted = sorted(score_data["blue_scores"].keys(),
                         key=lambda x: score_data["blue_scores"][x], reverse=True)

    def _fill(nums, target, n_max):
        seen = set(nums)
        while len(nums) < target:
            candidate = random.randint(1, n_max)
            if candidate not in seen:
                nums.append(candidate); seen.add(candidate)
        return sorted(nums[:target])

    return {
        "red": _fill(red_sorted, top_red, cfg["red_max"]),
        "blue": _fill(blue_sorted, top_blue, cfg["blue_max"]),
        "freq_support": score_data["freq_support"],
        "quality_avg": score_data["quality_avg"],
    }


# ============ 复试展开 ============

def _expand_combinations(red_pool, blue_pool, pick_red, pick_blue) -> list:
    """
    把复试号码池展开为全部注（笛卡尔积）。
    返回 [{"red": [...], "blue": [...]}, ...]
    """
    red_combos = list(combinations(sorted(red_pool), pick_red))
    blue_combos = list(combinations(sorted(blue_pool), pick_blue))
    details = []
    for rc in red_combos:
        for bc in blue_combos:
            details.append({"red": list(rc), "blue": list(bc)})
    return details


# ============ 生成多档方案 ============

async def generate_fushi(lottery_type: str, forecast_date: Optional[date] = None) -> dict:
    """
    生成某开奖期的多档复试方案 → upsert 到 hit_analysis 表。

    双色球：7+1, 7+2, 8+1, 8+2, 8+3, 9+1, 9+2, 9+3, 10+1, 10+2, 10+3 共 11 档
    大乐透：6+2, 6+3, 7+2, 7+3, 8+2, 8+3, 9+2 共 7 档

    Args:
        lottery_type: 'ssq' 或 'dlt'
        forecast_date: 指定日期，不传取当前目标开奖日

    Returns:
        {"forecast_date": str, "plans": [...], "skipped": bool, "message": str}
    """
    assert lottery_type in LOTTERY_CONFIG

    # 兼容字符串日期（预测接口回传 "%Y-%m-%d" 字符串）
    if isinstance(forecast_date, str):
        forecast_date = date.fromisoformat(forecast_date)

    if forecast_date is None:
        forecast_date = get_target_draw_date(lottery_type)
    if forecast_date is None:
        return {"skipped": True, "message": "没有找到当前目标开奖日"}

    cfg = LOTTERY_CONFIG[lottery_type]
    patterns = PATTERNS_BY_LOTTERY[lottery_type]

    # 1. 计算全号码频率分数表（GA 搜索空间）
    score_data = await _compute_freq_scores(lottery_type, forecast_date, use_quality_weight=True)
    if score_data is None:
        return {
            "skipped": True,
            "forecast_date": forecast_date.strftime("%Y-%m-%d"),
            "message": f"{forecast_date} 当天没有预测记录，无法生成复试",
        }

    # 2. 加载近 N 期历史开奖号（GA 适应度里的回测项）
    history_draws = await _load_recent_history_draws(lottery_type, n_periods=30)

    # 3. 多档方案 → 每档独立跑 GA → 展开 → 入库
    from app.services.ga_optimizer import GAOptimizer, GAConfig

    plans = []
    skipped_patterns = []
    optimized_pools_meta: List[Dict] = []   # 已优化档位的号码池，供下一档差异化惩罚

    async with AsyncSessionLocal() as db:
        for red_n, blue_n, pattern in patterns:
            # 构造 GA 配置
            ga_cfg = GAConfig(
                lottery_type=lottery_type,
                red_max=cfg["red_max"],
                blue_max=cfg["blue_max"],
                pick_red=cfg["pick_red"],
                pick_blue=cfg["pick_blue"],
                ball_unit=cfg["ball_unit"],
                red_freq_scores=score_data["red_scores"],
                blue_freq_scores=score_data["blue_scores"],
                red_pool_size=red_n,
                blue_pool_size=blue_n,
                history_draws=history_draws,
                optimized_pools=optimized_pools_meta,
            )

            # 跑 GA（同一档位同一期固定 seed 可复现，用 pattern 编码作 seed）
            seed = hash((lottery_type, forecast_date, pattern)) & 0x7FFFFFFF
            ga = GAOptimizer(ga_cfg, seed=seed)
            best_chrom, ga_meta = ga.run()

            red_truncated = sorted(best_chrom.red_genes)
            blue_truncated = sorted(best_chrom.blue_genes)

            # 展开
            details = _expand_combinations(
                red_truncated, blue_truncated,
                cfg["pick_red"], cfg["pick_blue"],
            )
            bet_count = len(details)
            bet_amount = bet_count * cfg["ball_unit"]

            # 金额上限保护（None=不限制）
            if MAX_BET_COUNT_PER_PATTERN is not None and bet_count > MAX_BET_COUNT_PER_PATTERN:
                skipped_patterns.append(f"{pattern}({bet_count}注超上限{MAX_BET_COUNT_PER_PATTERN})")
                continue

            # upsert
            existing = (await db.execute(
                select(HitAnalysis).where(
                    HitAnalysis.lottery_type == lottery_type,
                    HitAnalysis.forecast_date == forecast_date,
                    HitAnalysis.pattern == pattern,
                )
            )).scalar_one_or_none()

            if existing is None:
                obj = HitAnalysis(
                    lottery_type=lottery_type,
                    forecast_date=forecast_date,
                    pattern=pattern,
                    red_pool=red_truncated,
                    blue_pool=blue_truncated,
                    combo_detail=details,
                    bet_count=bet_count,
                    bet_amount=bet_amount,
                    freq_support=score_data["freq_support"],
                    quality_avg=score_data["quality_avg"],
                    optimization_meta={
                        "strategy": "ga_integrated",
                        "ga_meta": ga_meta,
                    },
                )
                db.add(obj)
            else:
                existing.red_pool = red_truncated
                existing.blue_pool = blue_truncated
                existing.combo_detail = details
                existing.bet_count = bet_count
                existing.bet_amount = bet_amount
                existing.freq_support = score_data["freq_support"]
                existing.quality_avg = score_data["quality_avg"]
                existing.optimization_meta = {
                    "strategy": "ga_integrated",
                    "ga_meta": ga_meta,
                }

            plans.append({
                "pattern": pattern,
                "red_pool": red_truncated,
                "blue_pool": blue_truncated,
                "bet_count": bet_count,
                "bet_amount": bet_amount,
                "first_combo": details[0] if details else None,
                "freq_support": score_data["freq_support"],
                "quality_avg": score_data["quality_avg"],
                "ga_fitness": ga_meta.get("final_fitness"),
                "is_history_hit": existing.is_history_hit if existing else 0,
                "prize_level": existing.prize_level if existing else None,
            })

            # 记录当前档位号码池，给下一档做差异化惩罚
            optimized_pools_meta.append({
                "red_pool": red_truncated,
                "blue_pool": blue_truncated,
            })

        await db.commit()

    msg = f"✅ {lottery_type} 复试生成：date={forecast_date} 共 {len(plans)} 档"
    if skipped_patterns:
        msg += f"（已跳过：{', '.join(skipped_patterns)}）"
    logger.info(msg)

    return {
        "skipped": False,
        "forecast_date": forecast_date.strftime("%Y-%m-%d"),
        "lottery_type": lottery_type,
        "patterns_total": len(patterns),
        "patterns_skipped": len(skipped_patterns),
        "skipped_patterns": skipped_patterns,
        "plans": plans,
    }


# ============ 查询 ============

async def list_fushi(lottery_type: str, forecast_date: Optional[date] = None,
                     limit: int = 20) -> list:
    """
    查某期已生成的复试方案；forecast_date 不传时返回最新 N 期（每期返回全部档位）。
    """
    async with AsyncSessionLocal() as db:
        if forecast_date is not None:
            target_dates = [forecast_date]
        else:
            # 先取最新 N 个日期，再把这些日期的全部档位一次性取出（避免截断）
            date_rows = (await db.execute(
                select(HitAnalysis.forecast_date)
                .where(HitAnalysis.lottery_type == lottery_type)
                .group_by(HitAnalysis.forecast_date)
                .order_by(desc(HitAnalysis.forecast_date))
                .limit(limit)
            )).scalars().all()
            target_dates = list(date_rows)

        if not target_dates:
            return []

        rows = (await db.execute(
            select(HitAnalysis)
            .where(
                HitAnalysis.lottery_type == lottery_type,
                HitAnalysis.forecast_date.in_(target_dates),
            )
            .order_by(HitAnalysis.forecast_date.desc(), HitAnalysis.bet_count.asc())
        )).scalars().all()

    # 按 forecast_date 分组
    grouped = {}
    for r in rows:
        key = r.forecast_date.strftime("%Y-%m-%d") if r.forecast_date else None
        if key not in grouped:
            grouped[key] = {
                "forecast_date": key,
                "patterns": [],
            }
        grouped[key]["patterns"].append({
            "pattern": r.pattern,
            "red_pool": r.red_pool,
            "blue_pool": r.blue_pool,
            "bet_count": r.bet_count,
            "bet_amount": r.bet_amount,
            "freq_support": r.freq_support,
            "quality_avg": r.quality_avg,
            "is_history_hit": r.is_history_hit,
            "prize_level": r.prize_level,
            "prize_amount": r.prize_amount,
            "prize_detail": r.prize_detail,
            "float_prize_count": r.float_prize_count,
            "combo_detail": r.combo_detail,
            "hit_reds": r.hit_reds,
            "hit_blues": r.hit_blues,
        })

    result = list(grouped.values())
    result.sort(key=lambda x: x["forecast_date"] or "", reverse=True)

    if forecast_date is not None:
        return result[:1] if result else []
    return result


# ============ 历史命中评估 ============

# 奖级排序（数值越小奖级越高），用于正确挑出最高奖级
PRIZE_RANK = {
    "一等奖": 1, "二等奖": 2, "三等奖": 3, "四等奖": 4,
    "五等奖": 5, "六等奖": 6, "七等奖": 7, "八等奖": 8, "九等奖": 9,
}

# 固定奖金（元/注）；一、二等奖为浮动奖，不在表中
PRIZE_AMOUNT = {
    "ssq": {
        "三等奖": 3000,
        "四等奖": 200,
        "五等奖": 10,
        "六等奖": 5,
    },
    "dlt": {
        "三等奖": 10000,
        "四等奖": 3000,
        "五等奖": 300,
        "六等奖": 200,
        "七等奖": 100,
        "八等奖": 15,
        "九等奖": 5,
    },
}


def _judge_prize(lottery_type: str, red_hits: int, blue_hits: int) -> Optional[str]:
    """
    根据红蓝命中数判定奖级（严格按官方规则）。
    """
    if lottery_type == "ssq":
        # 双色球：红球 6 选，蓝球 1 选
        if red_hits == 6 and blue_hits == 1:
            return "一等奖"
        if red_hits == 6 and blue_hits == 0:
            return "二等奖"
        if red_hits == 5 and blue_hits == 1:
            return "三等奖"
        if (red_hits == 5 and blue_hits == 0) or (red_hits == 4 and blue_hits == 1):
            return "四等奖"
        if (red_hits == 4 and blue_hits == 0) or (red_hits == 3 and blue_hits == 1):
            return "五等奖"
        # 六等奖：蓝球中，红球 0/1/2 个
        if blue_hits == 1 and red_hits <= 2:
            return "六等奖"
        return None

    # 大乐透：前区 5 选，后区 2 选（官方 9 个奖级）
    if red_hits == 5 and blue_hits == 2:
        return "一等奖"
    if red_hits == 5 and blue_hits == 1:
        return "二等奖"
    if red_hits == 5 and blue_hits == 0:
        return "三等奖"
    if red_hits == 4 and blue_hits == 2:
        return "四等奖"
    if red_hits == 4 and blue_hits == 1:
        return "五等奖"
    if red_hits == 3 and blue_hits == 2:
        return "六等奖"
    if red_hits == 4 and blue_hits == 0:
        return "七等奖"
    if (red_hits == 3 and blue_hits == 1) or (red_hits == 2 and blue_hits == 2):
        return "八等奖"
    if (red_hits == 3 and blue_hits == 0) or (red_hits == 2 and blue_hits == 1) or \
       (red_hits == 1 and blue_hits == 2) or (red_hits == 0 and blue_hits == 2):
        return "九等奖"
    return None


def _prize_money(lottery_type: str, prize: Optional[str]) -> int:
    """单注固定奖金；一、二等奖为浮动奖，返回 0 由调用方单独标记。"""
    if not prize:
        return 0
    return PRIZE_AMOUNT.get(lottery_type, {}).get(prize, 0)


async def evaluate_fushi_history(lottery_type: str, issue_or_date) -> dict:
    """
    对某期已开奖的复试方案，计算历史命中评估并回填。

    Args:
        lottery_type: 'ssq' | 'dlt'
        issue_or_date: 开奖期号（int）或日期（date/str）

    Returns:
        {"updated_count": int, "date": str, "issue": str}
    """
    assert lottery_type in LOTTERY_CONFIG
    cfg = LOTTERY_CONFIG[lottery_type]

    # 1. 拿开奖号
    async with AsyncSessionLocal() as db:
        q_hist = select(cfg["history_model"]).order_by(desc(
            cfg["history_model"].issue_num))

        if isinstance(issue_or_date, int):
            q_hist = select(cfg["history_model"]).where(
                cfg["history_model"].issue_num == issue_or_date)
        else:
            # date 或 str(date)
            from datetime import date as _date_type
            target = issue_or_date if isinstance(issue_or_date, _date_type) else \
                _date_type.fromisoformat(str(issue_or_date))
            q_hist = select(cfg["history_model"]).where(
                cfg["history_model"].draw_date == target)

        hist = (await db.execute(q_hist)).scalar_one_or_none()

        if hist is None:
            return {"updated_count": 0, "message": "没找到这期开奖记录"}

        # 2. 拿所有 HitAnalysis
        red_win, blue_win = extract_history_numbers(lottery_type, hist)

        # 大乐透 extract_history_numbers 已返回 list；ssq blue 也是 list
        if lottery_type == "ssq":
            red_win = set(red_win)
            blue_win = set(blue_win) if isinstance(blue_win, list) else {blue_win}
        else:
            red_win = set(red_win)
            blue_win = set(blue_win)

        rows = (await db.execute(
            select(HitAnalysis).where(
                HitAnalysis.lottery_type == lottery_type,
                HitAnalysis.forecast_date == hist.draw_date,
            )
        )).scalars().all()
        draw_date = hist.draw_date

    # 3. 逐条评估 combo_detail（在本会话内重新查询再更新，确保改动可持久化）
    updated = 0
    total_prize = 0
    total_bet = 0
    async with AsyncSessionLocal() as db2:
        rows = (await db2.execute(
            select(HitAnalysis).where(
                HitAnalysis.lottery_type == lottery_type,
                HitAnalysis.forecast_date == draw_date,
            )
        )).scalars().all()

        for row in rows:
            details = row.combo_detail or []
            prize_dist = Counter()
            red_hit_dist = Counter()
            blue_hit_dist = Counter()
            prize_money_total = 0          # 固定奖级奖金合计
            float_prize_count = 0          # 一/二等奖注数（浮动奖，无法固定金额）

            for combo in details:
                reds = combo.get("red", [])
                blues = combo.get("blue", [])
                red_h = len(set(reds) & red_win)
                blue_h = len(set(blues) & blue_win)
                red_hit_dist[red_h] += 1
                blue_hit_dist[blue_h] += 1
                prize = _judge_prize(lottery_type, red_h, blue_h)
                if prize:
                    prize_dist[prize] += 1
                    money = _prize_money(lottery_type, prize)
                    if money:
                        prize_money_total += money
                    else:
                        float_prize_count += 1

            if prize_dist:
                # 按官方奖级高低排序取最高奖级（不能用字符串排序）
                top_prize = min(prize_dist.keys(), key=lambda p: PRIZE_RANK.get(p, 99))
            else:
                top_prize = None

            row.is_history_hit = 1 if prize_dist else 0
            row.prize_level = top_prize
            row.prize_amount = int(prize_money_total)
            row.prize_detail = dict(prize_dist)
            row.float_prize_count = int(float_prize_count)
            row.hit_reds = dict(red_hit_dist)
            row.hit_blues = dict(blue_hit_dist)
            total_prize += int(prize_money_total)
            total_bet += int(row.bet_amount or 0)
            updated += 1

        await db2.commit()

    return {
        "updated_count": updated,
        "forecast_date": hist.draw_date.strftime("%Y-%m-%d"),
        "issue_num": str(hist.issue_num),
        "draw_red": sorted(red_win),
        "draw_blue": sorted(blue_win),
        "total_prize_amount": total_prize,
        "total_bet_amount": total_bet,
        "profit": total_prize - total_bet,
    }
