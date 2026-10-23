# -*- coding: utf-8 -*-
"""
数据查询接口：获取历史开奖数据及统计信息。
增强：新增历史开奖自相似度分析接口。
"""
import asyncio
import statistics

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.dlt_history import DLTHistory
from app.models.ssq_history import SSQHistory
from app.services.analysis_service import self_similarity_sync
from app.services.number_utils import extract_history_numbers

router = APIRouter(prefix="/data", tags=["Data"])

# 历史自相似度结果缓存：{lottery_type: (最新期号, 完整响应)}
# 结果只取决于历史开奖，新期导入前不变；重复访问直接命中缓存
_SELF_SIM_CACHE = {}


@router.get("/ssq")
async def get_ssq_data(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """
    获取双色球历史数据，按期号降序排列。
    - limit: 返回记录条数
    - offset: 偏移量，用于分页
    """
    # 查询总记录数
    total_result = await db.execute(select(func.count()).select_from(SSQHistory))
    total = total_result.scalar_one()

    result = await db.execute(
        select(SSQHistory).order_by(desc(SSQHistory.issue_num)).offset(offset).limit(limit)
    )
    items = result.scalars().all()
    return {"total": total, "items": items}


@router.get("/ssq/latest")
async def get_latest_ssq(db: AsyncSession = Depends(get_db)):
    """获取最新一期双色球开奖数据"""
    result = await db.execute(select(SSQHistory).order_by(desc(SSQHistory.issue_num)).limit(1))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "No data")
    return row


@router.get("/dlt")
async def get_dlt_data(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """获取大乐透历史数据"""
    # 查询总记录数
    total_result = await db.execute(select(func.count()).select_from(DLTHistory))
    total = total_result.scalar_one()

    result = await db.execute(
        select(DLTHistory).order_by(desc(DLTHistory.issue_num)).offset(offset).limit(limit)
    )
    items = result.scalars().all()
    return {"total": total, "items": items}


@router.get("/dlt/latest")
async def get_latest_dlt(db: AsyncSession = Depends(get_db)):
    """获取最新一期大乐透开奖数据"""
    result = await db.execute(select(DLTHistory).order_by(desc(DLTHistory.issue_num)).limit(1))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(404, "No data")
    return row


# ==================== 走势图统计 ====================
# 彩种号码范围配置
_TREND_CONFIG = {
    'ssq': {'red_max': 33, 'blue_max': 16, 'red_pick': 6, 'blue_pick': 1,
            'red_small_max': 16},
    'dlt': {'red_max': 35, 'blue_max': 12, 'red_pick': 5, 'blue_pick': 2,
            'red_small_max': 17, 'blue_small_max': 6},
}


def _trend_extract(row, lottery_type):
    """
    从开奖记录提取 (红球列表, 蓝球列表)，统计字段缺失时由号码现算兜底。
    返回 (reds, blues, stats)，stats 含 sum/span/odd/even/small/big。
    """
    cfg = _TREND_CONFIG[lottery_type]
    reds, blues = extract_history_numbers(lottery_type, row)
    if lottery_type == 'ssq':
        sum_v, span_v = row.red_summation, row.red_span
        odd_v, even_v = row.red_odd_count, row.red_even_count
        small_v, big_v = row.red_small_count, row.red_big_count
        blue_sum_v, blue_span_v = None, None
    else:
        sum_v, span_v = row.front_summation, row.front_span
        odd_v, even_v = row.front_odd_count, row.front_even_count
        small_v, big_v = row.front_small_count, row.front_big_count
        blue_sum_v, blue_span_v = row.back_summation, row.back_span

    # 统计字段为空时现算，保证图表数据完整
    if sum_v is None:
        sum_v = sum(reds)
    if span_v is None:
        span_v = max(reds) - min(reds)
    if odd_v is None:
        odd_v = sum(1 for n in reds if n % 2 == 1)
    if even_v is None:
        even_v = len(reds) - odd_v
    if small_v is None:
        small_v = sum(1 for n in reds if n <= cfg['red_small_max'])
    if big_v is None:
        big_v = len(reds) - small_v
    if lottery_type == 'dlt':
        if blue_sum_v is None:
            blue_sum_v = sum(blues)
        if blue_span_v is None:
            blue_span_v = max(blues) - min(blues)

    stats = {
        "sum": int(sum_v), "span": int(span_v),
        "odd": int(odd_v), "even": int(even_v),
        "small": int(small_v), "big": int(big_v),
        "blue_sum": int(blue_sum_v) if blue_sum_v is not None else None,
        "blue_span": int(blue_span_v) if blue_span_v is not None else None,
    }
    return reds, blues, stats


@router.get("/trend/{lottery_type}")
async def get_trend_data(
    lottery_type: str,
    periods: int = Query(100, ge=10, le=500, description="统计窗口：最近 N 期"),
    db: AsyncSession = Depends(get_db)
):
    """
    走势图数据：号码频率、当前遗漏、和值/跨度走势序列、冷热号与形态分布。
    全部基于数据库真实开奖记录计算。
    """
    if lottery_type not in ('ssq', 'dlt'):
        raise HTTPException(400, "lottery_type 必须是 ssq 或 dlt")

    cfg = _TREND_CONFIG[lottery_type]
    model = SSQHistory if lottery_type == 'ssq' else DLTHistory

    # 历史总期数
    total_history = (await db.execute(select(func.count()).select_from(model))).scalar_one()

    # 最近 N 期（降序取出后反转为升序：旧 → 新）
    rows = (await db.execute(
        select(model).order_by(desc(model.issue_num)).limit(periods)
    )).scalars().all()
    rows = list(reversed(rows))
    if not rows:
        raise HTTPException(404, "暂无开奖数据")

    red_freq = {n: 0 for n in range(1, cfg['red_max'] + 1)}
    blue_freq = {n: 0 for n in range(1, cfg['blue_max'] + 1)}
    red_last_idx = {n: -1 for n in range(1, cfg['red_max'] + 1)}
    blue_last_idx = {n: -1 for n in range(1, cfg['blue_max'] + 1)}

    trend = []
    odd_total = even_total = small_total = big_total = 0
    sum_list, span_list = [], []

    for idx, row in enumerate(rows):
        reds, blues, stats = _trend_extract(row, lottery_type)
        for n in reds:
            red_freq[n] += 1
            red_last_idx[n] = idx
        for n in blues:
            blue_freq[n] += 1
            blue_last_idx[n] = idx
        odd_total += stats['odd']
        even_total += stats['even']
        small_total += stats['small']
        big_total += stats['big']
        sum_list.append(stats['sum'])
        span_list.append(stats['span'])
        trend.append({
            "issue_num": row.issue_num,
            "draw_date": row.draw_date.strftime("%Y-%m-%d") if row.draw_date else None,
            "sum": stats['sum'],
            "span": stats['span'],
            "odd": stats['odd'],
            "even": stats['even'],
            "small": stats['small'],
            "big": stats['big'],
            "blue_sum": stats['blue_sum'],
            "blue_span": stats['blue_span']
        })

    last_idx = len(rows) - 1
    # 遗漏：最新一期已出现为 0，窗口内从未出现则记为窗口长度
    red_missing = {n: (last_idx - red_last_idx[n]) if red_last_idx[n] >= 0 else len(rows)
                   for n in range(1, cfg['red_max'] + 1)}
    blue_missing = {n: (last_idx - blue_last_idx[n]) if blue_last_idx[n] >= 0 else len(rows)
                    for n in range(1, cfg['blue_max'] + 1)}

    def freq_list(freq):
        return [{"number": n, "count": freq[n]} for n in sorted(freq.keys())]

    def missing_list(missing):
        return [{"number": n, "missing": missing[n]} for n in sorted(missing.keys())]

    hot_red = sorted(freq_list(red_freq), key=lambda x: -x['count'])[:5]
    hot_blue = sorted(freq_list(blue_freq), key=lambda x: -x['count'])[:5]
    cold_red = sorted(missing_list(red_missing), key=lambda x: -x['missing'])[:5]
    cold_blue = sorted(missing_list(blue_missing), key=lambda x: -x['missing'])[:5]

    latest = rows[-1]
    return {
        "lottery_type": lottery_type,
        "periods": len(rows),
        "total_history": total_history,
        "latest_issue": latest.issue_num,
        "latest_date": latest.draw_date.strftime("%Y-%m-%d") if latest.draw_date else None,
        "red": {
            "max": cfg['red_max'],
            "frequency": freq_list(red_freq),
            "missing": missing_list(red_missing)
        },
        "blue": {
            "max": cfg['blue_max'],
            "frequency": freq_list(blue_freq),
            "missing": missing_list(blue_missing)
        },
        "trend": trend,
        "summary": {
            "avg_sum": round(sum(sum_list) / len(sum_list), 1),
            "avg_span": round(sum(span_list) / len(span_list), 1),
            "hot_red": hot_red,
            "hot_blue": hot_blue,
            "cold_red": cold_red,
            "cold_blue": cold_blue,
            "odd_even": {"odd": odd_total, "even": even_total},
            "big_small": {"big": big_total, "small": small_total}
        }
    }


# ==================== 历史开奖自相似度分析 ====================
@router.get("/similarity/{lottery_type}")
async def get_history_similarity(
    lottery_type: str,
    limit: int = Query(None, ge=0, le=10000, description="参与分析的最近 N 期，不传或传 0 表示全部"),
    db: AsyncSession = Depends(get_db)
):
    """
    历史开奖自相似度分析。
    逻辑：最新一期 vs 所有上期 → 第二新 vs 所有上期 → ... 以此类推。
    返回每条的最大相似度 + 汇总统计。
    相似度用位掩码 + numpy 向量化计算（O(N²) set 双重循环 → 亚秒级）；
    全量分析结果按最新期号缓存，新期导入前重复访问零计算。
    """
    if lottery_type not in ('ssq', 'dlt'):
        raise HTTPException(400, "lottery_type 必须是 ssq 或 dlt")

    # 全量分析（limit 为空/0）可按最新期号缓存
    use_cache = not (limit and limit > 0)
    if use_cache:
        cached = _SELF_SIM_CACHE.get(lottery_type)
        if cached is not None:
            return cached[1]

    hist_model = SSQHistory if lottery_type == 'ssq' else DLTHistory
    stmt = select(hist_model).order_by(desc(hist_model.issue_num))
    if limit and limit > 0:
        stmt = stmt.limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    rows = list(reversed(rows))  # 旧 → 新
    metas = []
    for r in rows:
        reds, blues = extract_history_numbers(lottery_type, r)
        metas.append({
            "issue_num": r.issue_num,
            "draw_date": r.draw_date.strftime("%Y-%m-%d") if r.draw_date else None,
            "red": tuple(reds),
            "blue": tuple(blues),
        })

    if len(metas) < 2:
        return {
            "lottery_type": lottery_type,
            "total": len(metas),
            "analyzed": 0,
            "items": [],
            "summary": None
        }

    # 纯 CPU 向量化计算放线程池，不阻塞事件循环
    items, all_sims = await asyncio.to_thread(self_similarity_sync, metas, lottery_type)

    # 汇总统计
    avg_sim = round(statistics.mean(all_sims), 4)
    median_sim = round(statistics.median(all_sims), 4)
    max_sim_overall = round(max(all_sims), 4)
    min_sim_overall = round(min(all_sims), 4)

    # 分布：<20%, 20-40%, 40-60%, 60-80%, ≥80%
    dist = {"<20%": 0, "20-40%": 0, "40-60%": 0, "60-80%": 0, "≥80%": 0}
    for s in all_sims:
        pct = s * 100
        if pct < 20:
            dist["<20%"] += 1
        elif pct < 40:
            dist["20-40%"] += 1
        elif pct < 60:
            dist["40-60%"] += 1
        elif pct < 80:
            dist["60-80%"] += 1
        else:
            dist["≥80%"] += 1

    # 最高相似度 TOP 10
    top10 = sorted(items, key=lambda x: x["max_similarity"], reverse=True)[:10]

    # 相似度 ≥40% 的条数（即用户之前的过滤阈值）
    high_sim_count = sum(1 for s in all_sims if s >= 0.40)

    summary = {
        "total_analyzed": len(all_sims),
        "avg_similarity": avg_sim,
        "median_similarity": median_sim,
        "max_similarity": max_sim_overall,
        "min_similarity": min_sim_overall,
        "high_similarity_count": high_sim_count,
        "high_similarity_rate": round(high_sim_count / len(all_sims) * 100, 1),
        "distribution": dist,
        "top10_similar": top10
    }

    payload = {
        "lottery_type": lottery_type,
        "total": len(metas),
        "analyzed": len(all_sims),
        "items": list(reversed(items)),  # 降序（最新的排前面）
        "summary": summary
    }
    if use_cache:
        _SELF_SIM_CACHE[lottery_type] = (metas[-1]["issue_num"], payload)
    return payload