# -*- coding: utf-8 -*-
"""
数据加载模块：从数据库读取历史数据并转换为特征矩阵。
同时提供异步和同步版本，异步供 FastAPI 使用，同步供 Celery 训练使用。

深度学习增强版：
- 数据库全字段利用（含字符串编码 + 移动窗口统计）
- 号码频率特征（每个号码近 10 期出现次数）
- 多标签分类目标编码（multi-hot）取代回归目标
- ssq: 99 维特征 + 49 维 multi-hot 目标 = 148 列
- dlt: 99 维特征 + 47 维 multi-hot 目标 = 146 列
"""
import numpy as np
import pandas as pd
from sqlalchemy import select, func, inspect as sa_inspect

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.dlt_history import DLTHistory
from app.models.ssq_history import SSQHistory


# ==================== 彩种配置 ====================
SSQ_RED_RANGE = 33
SSQ_BLUE_RANGE = 16
DLT_FRONT_RANGE = 35
DLT_BACK_RANGE = 12


# ==================== 数据库原始列名（用于从 raw DataFrame 选列） ====================
SSQ_DB_FEATURE_COLS = [
    'year', 'month', 'quarter', 'weekday',
    'red_summation', 'red_summation_tail', 'red_span',
    'red_max', 'red_min',
    'red_odd_count', 'red_even_count',
    'red_small_count', 'red_big_count',
    'red_prime_count', 'red_composite_count',
    'red_mod0_count', 'red_mod1_count', 'red_mod2_count',
    'red_zone1_count', 'red_zone2_count', 'red_zone3_count',
    'red_consecutive_groups', 'red_consecutive_max_len',
    'red_repeat_count',
    'red_ac_value', 'red_first_last_sum',
    'red_middle_avg', 'red_std_dev',
    'blue_odd_even', 'blue_size', 'blue_mod3', 'blue_mod4', 'blue_repeat_flag',
    'total_sum', 'total_odd_count', 'total_even_count',
    'total_small_count', 'total_big_count',
    'sum_ma5', 'sum_std5', 'span_ma5', 'ac_ma5', 'odd_ma5',
    'sum_ma10', 'sum_std10', 'span_ma10', 'ac_ma10', 'odd_ma10',
    'sum_diff1', 'special_pattern',
]  # 50 列

DLT_DB_FEATURE_COLS = [
    'year', 'month', 'quarter', 'weekday',
    'front_summation', 'front_summation_tail', 'front_span',
    'front_max', 'front_min',
    'front_odd_count', 'front_even_count',
    'front_small_count', 'front_big_count',
    'front_prime_count', 'front_composite_count',
    'front_mod0_count', 'front_mod1_count', 'front_mod2_count',
    'front_zone1_count', 'front_zone2_count', 'front_zone3_count',
    'front_consecutive_groups', 'front_consecutive_max_len',
    'front_repeat_count',
    'front_ac_value', 'front_first_last_sum',
    'front_middle_avg', 'front_std_dev',
    'back_odd_count', 'back_even_count',
    'back_span', 'back_summation', 'back_summation_tail',
    'back_small_count', 'back_big_count',
    'back_repeat_count', 'back_repeat_flag_front',
    'total_summation', 'total_odd_count', 'total_even_count',
    'sum_ma5', 'sum_std5', 'span_ma5', 'ac_ma5', 'odd_ma5',
    'sum_ma10', 'sum_std10', 'span_ma10', 'ac_ma10', 'odd_ma10',
    'sum_diff1', 'special_pattern',
]  # 52 列


# ==================== 特征工程：字符串字段编码 ====================
def _encode_string_fields(raw: pd.DataFrame, lottery_type: str) -> pd.DataFrame:
    """把数据库里的字符串分析字段编码为整数"""
    if raw.empty:
        return raw

    if lottery_type == 'ssq':
        raw['blue_odd_even'] = (
            raw['blue_odd_even'].astype(str).str.lower().eq('odd').astype(int)
        )
        raw['blue_size'] = (
            raw['blue_size'].astype(str).str.lower().eq('big').astype(int)
        )

    raw['special_pattern'] = pd.factorize(
        raw['special_pattern'].fillna('NONE').astype(str), sort=True
    )[0]
    return raw


# ==================== 特征工程：移动窗口统计 ====================
def _add_engineered_features(df: pd.DataFrame, lottery_type: str) -> pd.DataFrame:
    """在原 DataFrame 上叠加近 5/10 期移动统计特征"""
    if df.empty:
        return df

    if lottery_type == 'ssq':
        sum_col, span_col, ac_col, odd_col = 'red_summation', 'red_span', 'red_ac_value', 'red_odd_count'
    else:
        sum_col, span_col, ac_col, odd_col = 'front_summation', 'front_span', 'front_ac_value', 'front_odd_count'

    for c in (sum_col, span_col, ac_col, odd_col):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

    for w in (5, 10):
        df[f'sum_ma{w}'] = df[sum_col].rolling(w, min_periods=1).mean()
        df[f'sum_std{w}'] = df[sum_col].rolling(w, min_periods=1).std().fillna(0)
        df[f'span_ma{w}'] = df[span_col].rolling(w, min_periods=1).mean()
        df[f'ac_ma{w}'] = df[ac_col].rolling(w, min_periods=1).mean()
        df[f'odd_ma{w}'] = df[odd_col].rolling(w, min_periods=1).mean()

    df['sum_diff1'] = df[sum_col].diff().fillna(0)
    return df


# ==================== 特征工程：号码频率特征 ====================
def _add_number_frequency_features(raw: pd.DataFrame, lottery_type: str, window: int = 10) -> pd.DataFrame:
    """
    为每行添加号码频率特征：统计过去 window 期内每个号码出现的次数。
    SSQ: 33 个红球频率 + 16 个蓝球频率 = 49 维
    DLT: 35 个前区频率 + 12 个后区频率 = 47 维
    """
    if raw.empty:
        return raw

    if lottery_type == 'ssq':
        red_cols = ['red_one', 'red_two', 'red_three', 'red_four', 'red_five', 'red_six']
        blue_cols = ['blue_one']
        red_range, blue_range = SSQ_RED_RANGE, SSQ_BLUE_RANGE
    else:
        red_cols = ['front_one', 'front_two', 'front_three', 'front_four', 'front_five']
        blue_cols = ['back_one', 'back_two']
        red_range, blue_range = DLT_FRONT_RANGE, DLT_BACK_RANGE

    n = len(raw)
    row_idx = np.arange(n)

    # 用出现矩阵 + cumsum 向量化：freq[i] = sum(occ[max(0,i-window) : i])，与逐行循环语义一致
    def _build_freq(cols, num_range):
        occ = np.zeros((n, num_range), dtype=np.float32)
        for col in cols:
            if col in raw.columns:
                v = pd.to_numeric(raw[col], errors='coerce').fillna(0).astype(int).values
                valid = (v >= 1) & (v <= num_range)
                occ[row_idx[valid], v[valid] - 1] += 1.0
        csum = np.vstack([np.zeros((1, num_range), dtype=np.float32), np.cumsum(occ, axis=0)])
        hi = np.arange(1, n + 1)
        lo = np.maximum(hi - window, 0)
        return csum[hi] - csum[lo]

    red_freq = _build_freq(red_cols, red_range)
    blue_freq = _build_freq(blue_cols, blue_range)

    for k in range(red_range):
        raw[f'freq_r{k+1}'] = red_freq[:, k]
    for k in range(blue_range):
        raw[f'freq_b{k+1}'] = blue_freq[:, k]

    return raw


# ==================== 多标签目标编码 ====================
def _build_multihot_targets(raw: pd.DataFrame, lottery_type: str) -> np.ndarray:
    """
    将实际开奖号码转为 multi-hot 编码。
    SSQ: 33 维红球 multi-hot + 16 维蓝球 multi-hot = 49 维
    DLT: 35 维前区 multi-hot + 12 维后区 multi-hot = 47 维
    """
    if lottery_type == 'ssq':
        red_cols = ['red_one', 'red_two', 'red_three', 'red_four', 'red_five', 'red_six']
        blue_cols = ['blue_one']
        red_range, blue_range = SSQ_RED_RANGE, SSQ_BLUE_RANGE
    else:
        red_cols = ['front_one', 'front_two', 'front_three', 'front_four', 'front_five']
        blue_cols = ['back_one', 'back_two']
        red_range, blue_range = DLT_FRONT_RANGE, DLT_BACK_RANGE

    n = len(raw)
    red_mh = np.zeros((n, red_range), dtype=np.float32)
    blue_mh = np.zeros((n, blue_range), dtype=np.float32)
    row_idx = np.arange(n)

    # 向量化 multi-hot：按列一次性提取号码值，再用花式索引填充
    for col in red_cols:
        if col in raw.columns:
            v = pd.to_numeric(raw[col], errors='coerce').fillna(0).astype(int).values
            valid = (v >= 1) & (v <= red_range)
            red_mh[row_idx[valid], v[valid] - 1] = 1.0
    for col in blue_cols:
        if col in raw.columns:
            v = pd.to_numeric(raw[col], errors='coerce').fillna(0).astype(int).values
            valid = (v >= 1) & (v <= blue_range)
            blue_mh[row_idx[valid], v[valid] - 1] = 1.0

    return np.concatenate([red_mh, blue_mh], axis=1)


# ==================== 统一构造特征+目标矩阵 ====================
def _build_feature_dataframe(raw: pd.DataFrame, lottery_type: str) -> pd.DataFrame:
    """
    从原始数据库 DataFrame 构造特征+目标 DataFrame（同步/异步共用）。
    输出列名使用短名常量（SSQ_FEATURE_COLS / DLT_FEATURE_COLS），与训练/预测维度对齐。
    """
    if raw is None or raw.empty:
        return pd.DataFrame()

    raw['weekday'] = pd.to_numeric(raw['weekday'], errors='coerce').fillna(1).astype(int)

    if lottery_type == 'ssq':
        for c in ('red_middle_avg', 'red_std_dev'):
            raw[c] = pd.to_numeric(raw[c], errors='coerce').fillna(0).astype(float)
        raw = _encode_string_fields(raw, 'ssq')
        raw = _add_engineered_features(raw, 'ssq')
        raw = _add_number_frequency_features(raw, 'ssq')

        db_cols = SSQ_DB_FEATURE_COLS
        freq_cols = [f'freq_r{k}' for k in range(1, SSQ_RED_RANGE + 1)] \
                   + [f'freq_b{k}' for k in range(1, SSQ_BLUE_RANGE + 1)]
        out_feature_names = SSQ_FEATURE_COLS
        out_target_names = SSQ_TARGET_COLS
    else:
        for c in ('front_middle_avg', 'front_std_dev'):
            raw[c] = pd.to_numeric(raw[c], errors='coerce').fillna(0).astype(float)
        raw = _encode_string_fields(raw, 'dlt')
        raw = _add_engineered_features(raw, 'dlt')
        raw = _add_number_frequency_features(raw, 'dlt')

        db_cols = DLT_DB_FEATURE_COLS
        freq_cols = [f'freq_r{k}' for k in range(1, DLT_FRONT_RANGE + 1)] \
                   + [f'freq_b{k}' for k in range(1, DLT_BACK_RANGE + 1)]
        out_feature_names = DLT_FEATURE_COLS
        out_target_names = DLT_TARGET_COLS

    # 从 raw 中选列：DB 原始列名 + 频率列名
    select_cols = db_cols + freq_cols
    features = raw[select_cols].fillna(0).values.astype(np.float32)

    # 构造多标签目标
    targets = _build_multihot_targets(raw, lottery_type)

    # 拼接，输出列名使用短名常量
    data = np.concatenate([features, targets], axis=1)
    out_cols = out_feature_names + out_target_names
    return pd.DataFrame(data, columns=out_cols)


# ==================== 特征级缓存（数据未更新时直接复用，避免每次预测重建） ====================
_FEATURE_CACHE = {}  # lottery_type -> (max_issue_num, DataFrame)


def _cached_features(lottery_type: str, max_issue) -> pd.DataFrame:
    """缓存命中则返回副本，未命中返回 None"""
    cached = _FEATURE_CACHE.get(lottery_type)
    if cached is not None and max_issue is not None and cached[0] == max_issue:
        return cached[1].copy()
    return None


# ==================== 异步版本（供 FastAPI 使用） ====================
async def _get_max_issue_async(lottery_type: str):
    model = SSQHistory if lottery_type == 'ssq' else DLTHistory
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(func.max(model.issue_num)))
        return result.scalar()


async def load_ssq_data(limit: int = None) -> pd.DataFrame:
    """异步加载双色球历史数据"""
    return await _load_features_async('ssq', limit)


async def load_dlt_data(limit: int = None) -> pd.DataFrame:
    """异步加载大乐透历史数据"""
    return await _load_features_async('dlt', limit)


async def _load_features_async(lottery_type: str, limit: int = None) -> pd.DataFrame:
    # 全量加载时先查最新期号（单行查询），命中缓存则跳过重建
    if limit is None:
        max_issue = await _get_max_issue_async(lottery_type)
        cached = _cached_features(lottery_type, max_issue)
        if cached is not None:
            return cached

    model = SSQHistory if lottery_type == 'ssq' else DLTHistory
    async with AsyncSessionLocal() as db:
        query = select(model).order_by(model.issue_num)
        if limit:
            query = query.limit(limit)
        result = await db.execute(query)
        rows = result.scalars().all()

    mapper = sa_inspect(model)
    col_names = [c.key for c in mapper.columns]
    raw = pd.DataFrame([{c: getattr(r, c, None) for c in col_names} for r in rows])
    df = _build_feature_dataframe(raw, lottery_type)

    if limit is None:
        _FEATURE_CACHE[lottery_type] = (await _get_max_issue_async(lottery_type), df)
        return df.copy()
    return df


# ==================== 同步版本（供 Celery 训练使用） ====================
def _load_raw_sync(lottery_type: str, limit: int = None) -> pd.DataFrame:
    """同步读取原始表（含全部字段）

    使用 SQLAlchemy Connection（而非 raw DBAPI 连接）传给 pd.read_sql，
    避免 pandas 对非 SQLAlchemy 连接发出的 UserWarning。
    """
    from app.core.database import sync_engine
    table = 'ssq_history' if lottery_type == 'ssq' else 'dlt_history'
    query = f"SELECT * FROM {table} ORDER BY issue_num"
    if limit:
        query += f" LIMIT {limit}"
    with sync_engine.connect() as conn:
        return pd.read_sql(query, conn)


def _get_max_issue_sync(lottery_type: str):
    """同步查询最新期号（单行查询，用于缓存命中判断）。

    数据库 issue_num 可能存字符串（VARCHAR '2026119'），
    这里统一转 int，让所有下游（回测、进化闸门）做期号算术都安全。
    """
    from app.core.database import sync_engine
    table = 'ssq_history' if lottery_type == 'ssq' else 'dlt_history'
    with sync_engine.connect() as conn:
        result = conn.exec_driver_sql(f"SELECT MAX(issue_num) FROM {table}")
        val = result.scalar()
        if val is None:
            return 0
        try:
            return int(val)
        except (TypeError, ValueError):
            # 极端兜底：字符串里可能混了非数字字符，尝试只取前导数字
            import re as _re
            m = _re.search(r'\d+', str(val))
            return int(m.group()) if m else 0


def get_max_issue_sync(lottery_type: str) -> int:
    """公开接口：查询某彩种历史表的最新期号（永远返回 int）"""
    return _get_max_issue_sync(lottery_type)


def load_ssq_data_sync(limit: int = None) -> pd.DataFrame:
    """同步加载双色球历史数据（供 Celery 训练/回测使用，带特征缓存）"""
    return _load_features_sync('ssq', limit)


def load_dlt_data_sync(limit: int = None) -> pd.DataFrame:
    """同步加载大乐透历史数据（供 Celery 训练/回测使用，带特征缓存）"""
    return _load_features_sync('dlt', limit)


def _load_features_sync(lottery_type: str, limit: int = None) -> pd.DataFrame:
    if limit is None:
        max_issue = _get_max_issue_sync(lottery_type)
        cached = _cached_features(lottery_type, max_issue)
        if cached is not None:
            return cached

    raw = _load_raw_sync(lottery_type, limit)
    df = _build_feature_dataframe(raw, lottery_type)

    if limit is None:
        _FEATURE_CACHE[lottery_type] = (_get_max_issue_sync(lottery_type), df)
        return df.copy()
    return df


# ==================== 输出列名常量（训练/预测维度对齐用） ====================
SSQ_FEATURE_COLS = [
    'year','month','quarter','weekday',
    'sum','sum_tail','span','red_max','red_min',
    'odd','even','small','big',
    'prime','composite','mod0','mod1','mod2',
    'zone1','zone2','zone3',
    'cons_groups','cons_max_len','repeat',
    'ac','first_last_sum','mid_avg','std_dev',
    'blue_odd_even','blue_size','blue_mod3','blue_mod4','blue_repeat',
    'total_sum','total_odd','total_even','total_small','total_big',
    'sum_ma5','sum_std5','span_ma5','ac_ma5','odd_ma5',
    'sum_ma10','sum_std10','span_ma10','ac_ma10','odd_ma10',
    'sum_diff1','special_pattern',
] + [f'freq_r{k}' for k in range(1, SSQ_RED_RANGE + 1)] \
  + [f'freq_b{k}' for k in range(1, SSQ_BLUE_RANGE + 1)]
# 总特征: 50 + 33 + 16 = 99

SSQ_TARGET_COLS = (
    [f'mh_r{k}' for k in range(1, SSQ_RED_RANGE + 1)]
    + [f'mh_b{k}' for k in range(1, SSQ_BLUE_RANGE + 1)]
)
# 总目标: 33 + 16 = 49


DLT_FEATURE_COLS = [
    'year','month','quarter','weekday',
    'sum','sum_tail','span','front_max','front_min',
    'odd','even','small','big',
    'prime','composite','mod0','mod1','mod2',
    'zone1','zone2','zone3',
    'cons_groups','cons_max_len','repeat',
    'ac','first_last_sum','mid_avg','std_dev',
    'back_odd','back_even','back_span','back_sum','back_sum_tail',
    'back_small','back_big','back_repeat','back_repeat_front',
    'total_sum','total_odd','total_even',
    'sum_ma5','sum_std5','span_ma5','ac_ma5','odd_ma5',
    'sum_ma10','sum_std10','span_ma10','ac_ma10','odd_ma10',
    'sum_diff1','special_pattern',
] + [f'freq_r{k}' for k in range(1, DLT_FRONT_RANGE + 1)] \
  + [f'freq_b{k}' for k in range(1, DLT_BACK_RANGE + 1)]
# 总特征: 52 + 35 + 12 = 99

DLT_TARGET_COLS = (
    [f'mh_r{k}' for k in range(1, DLT_FRONT_RANGE + 1)]
    + [f'mh_b{k}' for k in range(1, DLT_BACK_RANGE + 1)]
)
# 总目标: 35 + 12 = 47
