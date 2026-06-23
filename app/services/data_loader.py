# -*- coding: utf-8 -*-
"""
数据加载模块：从数据库读取历史数据并转换为特征矩阵。
"""
import pandas as pd
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.ssq_history import SSQHistory
from app.models.dlt_history import DLTHistory

async def load_ssq_data(limit: int = None) -> pd.DataFrame:
    """
    加载双色球历史数据，返回特征 DataFrame。
    特征包括：年份、月份、季度、和值、跨度、奇偶比等分析字段。
    """
    async with AsyncSessionLocal() as db:
        query = select(SSQHistory).order_by(SSQHistory.issue_num)
        if limit:
            query = query.limit(limit)
        result = await db.execute(query)
        rows = result.scalars().all()

    data = []
    for r in rows:
        # 提取分析特征（共 22 个，可根据需要调整）
        features = [
            r.year, r.month, r.quarter,
            r.red_summation, r.red_span,
            r.red_odd_count, r.red_even_count,
            r.red_small_count, r.red_big_count,
            r.red_prime_count, r.red_composite_count,
            r.red_mod0_count, r.red_mod1_count, r.red_mod2_count,
            r.red_zone1_count, r.red_zone2_count, r.red_zone3_count,
            r.red_ac_value,
            r.total_odd_count, r.total_even_count,
            r.red_repeat_count if hasattr(r, 'red_repeat_count') else 0,
            # 可添加蓝球相关特征，但预测目标是红球+蓝球，故可忽略或单独编码
        ]
        # 目标值：6个红球 + 1个蓝球
        target = [r.red_one, r.red_two, r.red_three, r.red_four, r.red_five, r.red_six, r.blue_one]
        data.append(features + target)

    columns = [
        'year','month','quarter','sum','span','odd','even','small','big',
        'prime','composite','mod0','mod1','mod2',
        'zone1','zone2','zone3','ac','total_odd','total_even','repeat',
        'r1','r2','r3','r4','r5','r6','b1'
    ]
    return pd.DataFrame(data, columns=columns)

async def load_dlt_data(limit: int = None) -> pd.DataFrame:
    """
    加载大乐透历史数据，返回特征 DataFrame。
    前区5个 + 后区2个。
    """
    async with AsyncSessionLocal() as db:
        query = select(DLTHistory).order_by(DLTHistory.issue_num)
        if limit:
            query = query.limit(limit)
        result = await db.execute(query)
        rows = result.scalars().all()

    data = []
    for r in rows:
        features = [
            r.year, r.month, r.quarter,
            r.front_summation, r.front_span,
            r.front_odd_count, r.front_even_count,
            r.front_small_count, r.front_big_count,
            r.front_prime_count, r.front_composite_count,
            r.front_mod0_count, r.front_mod1_count, r.front_mod2_count,
            r.front_zone1_count, r.front_zone2_count, r.front_zone3_count,
            r.front_ac_value,
            r.total_odd_count, r.total_even_count,
            r.front_repeat_count if hasattr(r, 'front_repeat_count') else 0,
            # 后区特征可加，但为简化只取基础
        ]
        target = [
            r.front_one, r.front_two, r.front_three, r.front_four, r.front_five,
            r.back_one, r.back_two
        ]
        data.append(features + target)

    columns = [
        'year','month','quarter','sum','span','odd','even','small','big',
        'prime','composite','mod0','mod1','mod2',
        'zone1','zone2','zone3','ac','total_odd','total_even','repeat',
        'f1','f2','f3','f4','f5','b1','b2'
    ]
    return pd.DataFrame(data, columns=columns)