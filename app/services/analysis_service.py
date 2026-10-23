# -*- coding: utf-8 -*-
"""
预测分析服务：整合预测记录，提取最优推荐号码，提供号码频率统计。
增强：对预测结果与历史开奖做相似度过滤，阈值根据历史自相似度分布动态计算。
"""
import asyncio
import logging
import random
import statistics
from collections import Counter, OrderedDict
from datetime import date, timedelta

import numpy as np
from sqlalchemy import select, text, desc, update, case

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.dlt_forecast import DLTForecast
from app.models.dlt_history import DLTHistory
from app.models.ssq_forecast import SSQForecast
from app.models.ssq_history import SSQHistory
from app.services.number_utils import extract_history_numbers, extract_forecast_numbers

logger = logging.getLogger(__name__)

# ==================== 开奖规则配置 ====================
LOTTERY_RULES = {
    'ssq': {
        'name': '双色球',
        'draw_days': [2, 4, 7],
        'draw_count': 3,
        'red_count': 6,
        'blue_count': 1,
        'red_max': 33,
        'blue_max': 16
    },
    'dlt': {
        'name': '大乐透',
        'draw_days': [1, 3, 6],
        'draw_count': 3,
        'red_count': 5,
        'blue_count': 2,
        'red_max': 35,
        'blue_max': 12
    }
}


def get_weekday_name(weekday):
    names = ['一', '二', '三', '四', '五', '六', '日']
    return names[weekday - 1] if 1 <= weekday <= 7 else str(weekday)


def is_holiday(target_date=None):
    """判断指定日期是否为休市日（国庆/春节等，休市期间无开奖）"""
    if target_date is None:
        target_date = date.today()
    return target_date in settings.lottery_holidays_set


def is_draw_day(lottery_type, target_date=None):
    if target_date is None:
        target_date = date.today()
    # 休市期间无开奖（即使星期几命中也返回 False）
    if is_holiday(target_date):
        return False
    weekday = target_date.isoweekday()
    rule = LOTTERY_RULES.get(lottery_type)
    if not rule:
        return False
    return weekday in rule['draw_days']


def get_next_draw_date(lottery_type, from_date=None):
    if from_date is None:
        from_date = date.today()
    rule = LOTTERY_RULES.get(lottery_type)
    if not rule:
        return None
    if is_draw_day(lottery_type, from_date):
        return from_date
    # 向后查找下一个开奖日，跳过休市期（最多看 30 天，覆盖最长休市如春节）
    for i in range(1, 31):
        next_date = from_date + timedelta(days=i)
        if is_draw_day(lottery_type, next_date):
            return next_date
    return None


def get_target_draw_date(lottery_type):
    """获取当前期对应的开奖日期"""
    today = date.today()
    if is_draw_day(lottery_type, today):
        return today
    return get_next_draw_date(lottery_type, today)


async def get_today_forecasts(lottery_type='ssq'):
    """获取当前开奖期的所有预测记录（基于 forecast_date 字段），按模型时间戳降序排列"""
    async with AsyncSessionLocal() as db:
        target_date = get_target_draw_date(lottery_type)
        if target_date is None:
            return []
        if lottery_type == 'ssq':
            query = select(SSQForecast).where(
                SSQForecast.forecast_date == target_date
            ).order_by(SSQForecast.create_time.desc())
        else:
            query = select(DLTForecast).where(
                DLTForecast.forecast_date == target_date
            ).order_by(DLTForecast.create_time.desc())
        result = await db.execute(query)
        records = result.scalars().all()

        # 按模型文件名中的时间戳降序排序
        def extract_timestamp(record):
            name = record.model_version
            try:
                base = name.rsplit('.', 1)[0]
                ts = int(base.split('_')[-1])
                return ts
            except (ValueError, AttributeError):
                # 早期/异常命名无时间戳，排序时按最旧处理
                return 0

        records.sort(key=extract_timestamp, reverse=True)
        return records


async def analyze_best_recommendation(forecasts, lottery_type='ssq'):
    """从预测列表中提取最优号码"""
    if not forecasts:
        return None

    rule = LOTTERY_RULES.get(lottery_type)
    if not rule:
        return None

    num_red = rule['red_count']
    num_blue = rule['blue_count']
    red_upper = rule['red_max']
    blue_upper = rule['blue_max']

    red_counter = Counter()
    blue_counter = Counter()
    total_weight = 0.0

    for f in forecasts:
        weight = f.quality_score or 0.5
        reds, blues = extract_forecast_numbers(lottery_type, f)
        for r in reds:
            red_counter[r] += weight
        for b in blues:
            blue_counter[b] += weight
        total_weight += weight

    red_most = red_counter.most_common(num_red)
    blue_most = blue_counter.most_common(num_blue)

    recommended_reds = [num for num, _ in red_most]
    while len(recommended_reds) < num_red:
        missing = random.choice([x for x in range(1, red_upper + 1) if x not in recommended_reds])
        recommended_reds.append(missing)
    recommended_reds.sort()

    recommended_blues = [num for num, _ in blue_most]
    while len(recommended_blues) < num_blue:
        missing = random.choice([x for x in range(1, blue_upper + 1) if x not in recommended_blues])
        recommended_blues.append(missing)
    recommended_blues.sort()

    return {
        "red": recommended_reds,
        "blue": recommended_blues if len(recommended_blues) > 1 else recommended_blues[0],
        "confidence": round(total_weight / len(forecasts), 3) if forecasts else 0
    }


# ==================== 新增：号码频率统计分析 ====================
async def analyze_number_frequency(forecasts, lottery_type='ssq'):
    """
    分析预测记录中的号码出现频率，返回红球和蓝球的 TOP 排名
    """
    if not forecasts:
        return None

    rule = LOTTERY_RULES.get(lottery_type)
    if not rule:
        return None

    red_counter = Counter()
    blue_counter = Counter()
    total_count = len(forecasts)

    for f in forecasts:
        reds, blues = extract_forecast_numbers(lottery_type, f)

        for r in reds:
            red_counter[r] += 1
        for b in blues:
            blue_counter[b] += 1

    # 红球 TOP 15（按出现次数排序）
    red_top = []
    for num, count in red_counter.most_common(15):
        red_top.append({
            "number": num,
            "count": count,
            "rate": round(count / total_count * 100, 1)
        })

    # 蓝球 TOP 12（按出现次数排序）
    blue_top = []
    for num, count in blue_counter.most_common(12):
        blue_top.append({
            "number": num,
            "count": count,
            "rate": round(count / total_count * 100, 1)
        })

    # 获取最高评分的 TOP 5 模型
    top_models = sorted(forecasts, key=lambda x: x.quality_score or 0, reverse=True)[:10]
    top_models_data = []
    for f in top_models:
        reds, blues = extract_forecast_numbers(lottery_type, f)
        top_models_data.append({
            "model_name": f.model_version,
            "quality_score": f.quality_score,
            "red": reds,
            "blue": blues
        })

    return {
        "total_count": total_count,
        "red_top": red_top,
        "blue_top": blue_top,
        "top_models": top_models_data
    }


async def get_today_latest_result(lottery_type='ssq'):
    """获取今天开奖结果（如果已开奖）"""
    today = date.today()
    if not is_draw_day(lottery_type, today):
        return None

    async with AsyncSessionLocal() as db:
        if lottery_type == 'ssq':
            query = select(SSQHistory).where(
                SSQHistory.draw_date == today
            ).order_by(SSQHistory.issue_num.desc()).limit(1)
        else:
            query = select(DLTHistory).where(
                DLTHistory.draw_date == today
            ).order_by(DLTHistory.issue_num.desc()).limit(1)
        result = await db.execute(query)
        return result.scalar_one_or_none()


async def get_upcoming_draw_info(lottery_type='ssq'):
    """获取下一期开奖信息"""
    rule = LOTTERY_RULES.get(lottery_type)
    if not rule:
        return None
    today = date.today()
    next_draw = get_next_draw_date(lottery_type, today)
    if next_draw:
        days_until = (next_draw - today).days
        weekday_name = get_weekday_name(next_draw.isoweekday())
        return {
            "next_draw_date": next_draw.strftime("%Y-%m-%d"),
            "next_draw_weekday": f"星期{weekday_name}",
            "days_until": days_until,
            "is_today": days_until == 0
        }
    return None


# ==================== 历史相似度过滤 ====================
DEFAULT_THRESHOLD = 0.40  # 兜底默认值


def _calc_similarity(pred_red, pred_blue, hist_red, hist_blue):
    """
    计算预测与历史开奖的相似度（Jaccard 风格：交集/并集）。
    red 和 blue 合并计算，红球权重更高（红球命中占主要部分）。
    """
    # 红球交集
    red_intersect = len(set(pred_red) & set(hist_red))
    red_union = len(set(pred_red) | set(hist_red))

    # 蓝球交集
    if isinstance(pred_blue, (list, set)):
        pred_blue_set = set(pred_blue)
    else:
        pred_blue_set = {pred_blue}
    if isinstance(hist_blue, (list, set)):
        hist_blue_set = set(hist_blue)
    else:
        hist_blue_set = {hist_blue}
    blue_intersect = len(pred_blue_set & hist_blue_set)
    blue_union = len(pred_blue_set | hist_blue_set)

    # 综合：红球占 70%，蓝球占 30%
    red_sim = red_intersect / red_union if red_union > 0 else 0
    blue_sim = blue_intersect / blue_union if blue_union > 0 else 0
    return 0.7 * red_sim + 0.3 * blue_sim


# ==================== 位掩码向量化相似度（大数据量加速） ====================
# 号码范围小（红≤35、蓝≤16），把一组号码编码为一个整数位掩码（号码 n -> bit n-1），
# 交集 = popcount(a & b)；红蓝各自定长，故并集 = 2*选号数 - 交集，无需并集运算。
# numpy uint64 数组批量位运算 + 16 位查表 popcount，把 O(F*H) 的 Python set 双重循环
# （数千预测 × 数千历史 ≈ 千万次比较）降为向量运算，耗时从数十秒降到亚秒级。

_PC_LUT = np.array([bin(i).count('1') for i in range(1 << 16)], dtype=np.int16)


def _numbers_to_mask(numbers):
    """号码可迭代对象 -> 整数位掩码（号码 n 置第 n-1 位）"""
    m = 0
    for n in numbers:
        m |= 1 << (int(n) - 1)
    return m


def _popcount_arr(x):
    """uint64 数组按 16 位分块查表求 popcount（numpy 1.x 无 np.bitwise_count 的兼容实现）"""
    x = x.astype(np.uint64)
    return (_PC_LUT[(x & np.uint64(0xFFFF)).astype(np.int64)]
            + _PC_LUT[((x >> np.uint64(16)) & np.uint64(0xFFFF)).astype(np.int64)]
            + _PC_LUT[((x >> np.uint64(32)) & np.uint64(0xFFFF)).astype(np.int64)])


def _vec_max_similarity(pr_mask, pb_mask, hr_arr, hb_arr, red_count, blue_count):
    """
    单组预测号码对全部历史（位掩码数组）的最大相似度。
    返回 (max_sim, 命中历史行下标)；与 _calc_similarity 公式完全一致。
    """
    ri = _popcount_arr(hr_arr & np.uint64(pr_mask)).astype(np.float64)
    bi = _popcount_arr(hb_arr & np.uint64(pb_mask)).astype(np.float64)
    red_sim = ri / (2 * red_count - ri)
    blue_sim = bi / (2 * blue_count - bi)
    sim = 0.7 * red_sim + 0.3 * blue_sim
    k = int(np.argmax(sim))
    return float(sim[k]), k


def _history_to_masks(rows, lottery_type):
    """历史 ORM 行（任意顺序）-> (红掩码数组, 蓝掩码数组, 期号列表)，按行顺序对齐"""
    n = len(rows)
    hr = np.empty(n, dtype=np.uint64)
    hb = np.empty(n, dtype=np.uint64)
    issues = []
    for i, r in enumerate(rows):
        if lottery_type == 'ssq':
            hr[i] = _numbers_to_mask(
                (r.red_one, r.red_two, r.red_three, r.red_four, r.red_five, r.red_six))
            hb[i] = _numbers_to_mask((r.blue_one,))
        else:
            hr[i] = _numbers_to_mask(
                (r.front_one, r.front_two, r.front_three, r.front_four, r.front_five))
            hb[i] = _numbers_to_mask((r.back_one, r.back_two))
        issues.append(r.issue_num)
    return hr, hb, issues


def _forecast_masks_sync(forecast_items, hr, hb, issues, lottery_type):
    """
    批量计算每条预测对全部历史的最大相似度（纯 CPU，放线程池执行）。
    分块矩阵化：把 F 条预测 × H 期历史的比较拼成 (chunk, H) 二维数组一次性向量化，
    替代 F 次 Python→numpy 小调用；chunk 控制内存峰值（每块约几十 MB）。
    forecast_items: [(model_version, red_mask, blue_mask), ...]
    返回 {model_version: (max_sim, matched_issue)}。
    """
    rule = LOTTERY_RULES[lottery_type]
    rc, bc = rule['red_count'], rule['blue_count']
    hr = hr.astype(np.uint64)
    hb = hb.astype(np.uint64)
    versions = [mv for mv, _, _ in forecast_items]
    pr_all = np.array([m for _, m, _ in forecast_items], dtype=np.uint64)
    pb_all = np.array([m for _, _, m in forecast_items], dtype=np.uint64)

    out = {}
    CHUNK = 256
    denom_r = 2 * rc
    denom_b = 2 * bc
    for s in range(0, len(forecast_items), CHUNK):
        pr = pr_all[s:s + CHUNK, None]  # (c,1) 广播
        pb = pb_all[s:s + CHUNK, None]
        ri = _popcount_arr(hr[None, :] & pr).astype(np.float64)  # (c,H)
        bi = _popcount_arr(hb[None, :] & pb).astype(np.float64)
        red_sim = ri / (denom_r - ri)
        blue_sim = bi / (denom_b - bi)
        sim = 0.7 * red_sim + 0.3 * blue_sim
        kidx = np.argmax(sim, axis=1)
        rows = np.arange(sim.shape[0])
        sval = sim[rows, kidx]
        for j, mv in enumerate(versions[s:s + CHUNK]):
            out[mv] = (round(float(sval[j]), 4), issues[int(kidx[j])])
    return out


def self_similarity_sync(metas, lottery_type):
    """
    历史自相似度（纯 CPU，放线程池）：第 i 期 vs 所有早期，取最大相似度。
    metas（旧→新）: [{"issue_num", "red": (红...), "blue": (蓝...)}, ...]
    返回 (items, all_sims)，items 每项含 issue_num/max_similarity/matched_history_issue/red/blue。
    """
    rule = LOTTERY_RULES[lottery_type]
    rc, bc = rule['red_count'], rule['blue_count']
    n = len(metas)
    hr = np.empty(n, dtype=np.uint64)
    hb = np.empty(n, dtype=np.uint64)
    for i, m in enumerate(metas):
        hr[i] = _numbers_to_mask(m["red"])
        hb[i] = _numbers_to_mask(m["blue"])

    items, all_sims = [], []
    for i in range(1, n):
        ri = _popcount_arr(hr[:i] & hr[i]).astype(np.float64)
        bi = _popcount_arr(hb[:i] & hb[i]).astype(np.float64)
        sim = 0.7 * ri / (2 * rc - ri) + 0.3 * bi / (2 * bc - bi)
        k = int(np.argmax(sim))
        max_sim = float(sim[k])
        all_sims.append(max_sim)
        items.append({
            "issue_num": metas[i]["issue_num"],
            "draw_date": metas[i].get("draw_date"),
            "red": sorted(metas[i]["red"]),
            "blue": sorted(metas[i]["blue"]),
            "max_similarity": round(max_sim, 4),
            "matched_history_issue": metas[k]["issue_num"],
        })
    return items, all_sims


# 动态阈值缓存：{lottery_type: (最新期号, 阈值)}，历史不变则阈值不变，新期导入自动失效
_THRESHOLD_CACHE = {}


def _threshold_from_masks(lottery_type, hr, hb, issues, sample_size=300):
    """由历史掩码数组计算动态阈值（mean + 1*std，clamp [0.25, 0.60]），带期号缓存"""
    latest = issues[-1] if issues else None
    cached = _THRESHOLD_CACHE.get(lottery_type)
    if cached is not None and cached[0] == latest:
        return cached[1]
    if len(hr) < 3:
        return DEFAULT_THRESHOLD

    rule = LOTTERY_RULES[lottery_type]
    rc, bc = rule['red_count'], rule['blue_count']
    hr_s, hb_s = hr[-sample_size:], hb[-sample_size:]  # 最近 sample_size 期（旧→新）

    sims = []
    for i in range(1, len(hr_s)):
        max_sim, _ = _vec_max_similarity(
            int(hr_s[i]), int(hb_s[i]), hr_s[:i], hb_s[:i], rc, bc)
        sims.append(max_sim)
    if not sims:
        return DEFAULT_THRESHOLD

    threshold = statistics.mean(sims) + (statistics.stdev(sims) if len(sims) > 1 else 0)
    threshold = max(0.25, min(0.60, threshold))
    threshold = round(threshold, 4)
    _THRESHOLD_CACHE[lottery_type] = (latest, threshold)
    return threshold


async def compute_dynamic_threshold(lottery_type='ssq', sample_size=300):
    """
    根据历史开奖自相似度分布，动态计算过滤阈值。
    取最近 sample_size 期，计算每期与所有上期的最大相似度，
    阈值 = mean + 1*std（约 84 分位），并 clamp 到 [0.25, 0.60]。
    结果按最新期号缓存，新期导入前不重复计算。
    """
    async with AsyncSessionLocal() as db:
        if lottery_type == 'ssq':
            result = await db.execute(
                select(SSQHistory).order_by(SSQHistory.issue_num)
            )
        else:
            result = await db.execute(
                select(DLTHistory).order_by(DLTHistory.issue_num)
            )
        rows = result.scalars().all()

    if len(rows) < 3:
        return DEFAULT_THRESHOLD
    hr, hb, issues = _history_to_masks(rows, lottery_type)
    return _threshold_from_masks(lottery_type, hr, hb, issues, sample_size=sample_size)


# 历史掩码缓存：{lottery_type: (最新期号, hr, hb, issues)}。
# 历史开奖只在新期导入时变化，用最新期号做失效键，避免每次分析都全量加载/转换数千行 ORM。
_HISTORY_MASK_CACHE = {}


async def _load_history_masks(lottery_type):
    """加载全部历史开奖（升序）并转为位掩码数组，返回 (hr, hb, issues)；无数据返回 None。
    带最新期号缓存：新期导入后 latest 变化自动重载，同周期内重复请求零 DB 开销。"""
    hist_model = SSQHistory if lottery_type == 'ssq' else DLTHistory
    async with AsyncSessionLocal() as db:
        # 先轻量取最新期号做缓存失效判断
        latest = (await db.execute(
            select(hist_model.issue_num).order_by(hist_model.issue_num.desc()).limit(1)
        )).scalar_one_or_none()
        if latest is None:
            return None
        cached = _HISTORY_MASK_CACHE.get(lottery_type)
        if cached is not None and cached[0] == latest:
            return cached[1], cached[2], cached[3]
        result = await db.execute(select(hist_model).order_by(hist_model.issue_num))
        rows = result.scalars().all()

    masks = _history_to_masks(rows, lottery_type)
    _HISTORY_MASK_CACHE[lottery_type] = (latest, masks[0], masks[1], masks[2])
    return masks


async def filter_by_history_similarity(forecasts, lottery_type='ssq'):
    """
    计算预测列表与历史开奖的相似度（位掩码 + numpy 向量化，亚秒级）。
    阈值根据历史自相似度分布动态计算（mean + 1*std），按最新期号缓存。
    相似度剔除功能已下线：所有预测全部保留，仅返回 sim_info 供展示与落库。
    返回 (forecasts(全部), [], sim_info, threshold)。
    """
    if not forecasts:
        return forecasts, [], {}, DEFAULT_THRESHOLD

    # 历史只加载一次，阈值与相似度共用同一份掩码
    masks = await _load_history_masks(lottery_type)
    if masks is None:
        return forecasts, [], {}, DEFAULT_THRESHOLD
    hr, hb, issues = masks
    threshold = _threshold_from_masks(lottery_type, hr, hb, issues)

    # 组装预测掩码（ORM 属性在事件循环内读取）
    forecast_items = []
    for f in forecasts:
        pred_red, blue_nums = extract_forecast_numbers(lottery_type, f)
        forecast_items.append(
            (f.model_version, _numbers_to_mask(pred_red), _numbers_to_mask(blue_nums)))

    # 纯 CPU 向量化计算放线程池，不阻塞事件循环
    sim_results = await asyncio.to_thread(
        _forecast_masks_sync, forecast_items, hr, hb, issues, lottery_type)

    # 不进行相似度剔除：全部预测保留，仅收集相似度信息
    sim_info = {}
    for f in forecasts:
        max_sim, matched_issue = sim_results[f.model_version]
        sim_info[f.model_version] = {
            "max_similarity": max_sim,
            "matched_history_issue": matched_issue
        }

    # 相似度信息回写 forecast 表（is_removed 恒为 0，不再剔除）。
    # 结果只取决于预测号码 + 历史开奖，同一开奖日、同一最新历史期、同一预测数量下结果不变，
    # 用幂等标记保证只写一次，避免每次打开分析页都执行 N 条巨型 CASE UPDATE（大数据量超时主因之一）。
    latest_issue = issues[-1] if issues else None
    persist_key = (lottery_type, forecasts[0].forecast_date, latest_issue, len(forecasts))
    if persist_key not in _PERSISTED_MARKS:
        await _persist_similarity_marks(lottery_type, forecasts, sim_info)
        _PERSISTED_MARKS.add(persist_key)
        # 有界保护：长期运行累积过多 key 时清空（key 本身随日期/期号变化失效）
        if len(_PERSISTED_MARKS) > _PERSISTED_MARKS_MAX:
            _PERSISTED_MARKS.clear()
            _PERSISTED_MARKS.add(persist_key)

    return list(forecasts), [], sim_info, threshold


# 相似度标记落库幂等集合：{(lottery_type, forecast_date, latest_history_issue, forecast_count)}
_PERSISTED_MARKS = set()
_PERSISTED_MARKS_MAX = 500


async def _persist_similarity_marks(lottery_type, forecasts, sim_info):
    """
    把相似度分析结果批量回写到 forecast 表：max_similarity / matched_history_issue。
    相似度剔除功能已下线，is_removed 恒写 0（全部保留）。
    使用 SQLAlchemy Core update() + case() 表达式（每批 200 行一条语句），由编译器原生绑定参数，
    把 N 次 ORM 逐条 UPDATE（远程 MySQL 数千次往返，易超时/参数解析异常）降为 ceil(N/200) 条语句。
    """
    if not forecasts:
        return
    model = SSQForecast if lottery_type == 'ssq' else DLTForecast
    table = model.__table__
    forecast_date = forecasts[0].forecast_date

    # 组装需要写入的值（model_version -> (max_similarity, matched_issue)）
    updates = []
    for f in forecasts:
        sim = sim_info.get(f.model_version, {})
        max_sim = round(float(sim.get("max_similarity", 0) or 0), 4)
        matched = sim.get("matched_history_issue")
        matched_str = str(matched) if matched else None
        updates.append((f.model_version, max_sim, matched_str))

    batch_size = 200
    async with AsyncSessionLocal() as db:
        for start in range(0, len(updates), batch_size):
            batch = updates[start:start + batch_size]
            sim_map = {ver: ms for ver, ms, _ in batch}
            matched_map = {ver: mi for ver, _, mi in batch}
            versions = [v for v, _, _ in batch]

            stmt = (
                update(table)
                .where(table.c.forecast_date == forecast_date,
                       table.c.model_version.in_(versions))
                .values(
                    is_removed=0,
                    max_similarity=case(
                        sim_map, value=table.c.model_version,
                        else_=table.c.max_similarity),
                    matched_history_issue=case(
                        matched_map, value=table.c.model_version,
                        else_=table.c.matched_history_issue),
                )
            )
            await db.execute(stmt)
        await db.commit()


# ==================== 全组合表 ID 查询 ====================
async def lookup_all_table_id(lottery_type, reds, blues):
    """
    在 ssq_all / dlt_all 全组合表中查询匹配的 id。
    ssq_all: red_one..red_six + blue_one
    dlt_all: front_one..front_five + back_one + back_two（但 forecast 存为 red/blue）
    返回 id（找不到返回 None）。
    """
    reds_sorted = sorted(reds)
    if isinstance(blues, list):
        blues_sorted = sorted(blues)
    else:
        blues_sorted = [blues]

    async with AsyncSessionLocal() as db:
        if lottery_type == 'ssq':
            sql = text("""
                SELECT id FROM ssq_all
                WHERE red_one = :r1 AND red_two = :r2 AND red_three = :r3
                  AND red_four = :r4 AND red_five = :r5 AND red_six = :r6
                  AND blue_one = :b1
                LIMIT 1
            """)
            params = {
                'r1': reds_sorted[0], 'r2': reds_sorted[1], 'r3': reds_sorted[2],
                'r4': reds_sorted[3], 'r5': reds_sorted[4], 'r6': reds_sorted[5],
                'b1': blues_sorted[0]
            }
        else:
            sql = text("""
                SELECT id FROM dlt_all
                WHERE front_one = :r1 AND front_two = :r2 AND front_three = :r3
                  AND front_four = :r4 AND front_five = :r5
                  AND back_one = :b1 AND back_two = :b2
                LIMIT 1
            """)
            params = {
                'r1': reds_sorted[0], 'r2': reds_sorted[1], 'r3': reds_sorted[2],
                'r4': reds_sorted[3], 'r5': reds_sorted[4],
                'b1': blues_sorted[0], 'b2': blues_sorted[1]
            }

        result = await db.execute(sql, params)
        row = result.fetchone()
        return row[0] if row else None


# 全组合表列定义（号码列均按升序存储）
_ALL_TABLE_COLS = {
    'ssq': ('ssq_all', ('red_one', 'red_two', 'red_three', 'red_four', 'red_five',
                        'red_six', 'blue_one')),
    'dlt': ('dlt_all', ('front_one', 'front_two', 'front_three', 'front_four', 'front_five',
                        'back_one', 'back_two')),
}

# 全组合表是静态表（号码组合 -> id 的映射永不变），用有界 LRU 缓存查询结果，
# 同一预测组合重复出现 / 重复打开分析页时零 DB 开销；容量上限防内存膨胀。
_COMBO_ID_CACHE = {'ssq': OrderedDict(), 'dlt': OrderedDict()}
_COMBO_ID_CACHE_MAX = 50000
# 全组合表空表标记（三态）：None=未知，True=空表(直接短路不查询)，False=有数据。
# 全组合为离线导入的静态表，导入后需重启服务生效。
_COMBO_TABLE_EMPTY = {'ssq': None, 'dlt': None}


async def bulk_lookup_all_table_ids(lottery_type, combos, chunk_size=200):
    """
    批量查询全组合表 ID：单会话 + 元组 IN 分块查询 + 进程内有界 LRU。
    - 全组合表为空（尚未导入）时直接返回空 dict，不发查询；
    - 先规范化去重，命中缓存的组合直接取（静态表 id 永不变）；
    - 仅对未命中的组合分块查询数据库，结果回填缓存。
    combos: [(reds_list, blues_list_or_int), ...]
    返回 {((红升序...), (蓝升序...)): id}，未命中的组合不在 dict 中。
    """
    table, cols = _ALL_TABLE_COLS[lottery_type]

    # 空表短路：全组合数据未导入时直接返回，避免每次分析都打空表
    if _COMBO_TABLE_EMPTY[lottery_type] is True:
        return {}

    # 去重 + 规范化（号码列在表中按升序存储）
    keys = set()
    for reds, blues in combos:
        red_key = tuple(sorted(reds))
        blue_key = tuple(sorted(blues)) if isinstance(blues, (list, tuple, set)) else (blues,)
        keys.add((red_key, blue_key))
    keys = list(keys)

    cache = _COMBO_ID_CACHE[lottery_type]
    result_map = {}
    missing = []
    for k in keys:
        if k in cache:
            val = cache[k]
            cache.move_to_end(k)
            if val is not None:
                result_map[k] = val
        else:
            missing.append(k)

    # 仅查询未命中缓存的组合
    if missing:
        # 首次访问确认全组合表是否已导入数据
        if _COMBO_TABLE_EMPTY[lottery_type] is None:
            async with AsyncSessionLocal() as db:
                cnt = (await db.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar()
            _COMBO_TABLE_EMPTY[lottery_type] = (cnt == 0)
            if cnt == 0:
                logger.info("全组合表 %s 为空，跳过 ID 查询（导入数据后重启服务生效）", table)
                return {}

        n_red = 6 if lottery_type == 'ssq' else 5
        async with AsyncSessionLocal() as db:
            for start in range(0, len(missing), chunk_size):
                chunk = missing[start:start + chunk_size]
                params = {}
                placeholders = []
                for idx, (red_key, blue_key) in enumerate(chunk):
                    vals = list(red_key) + list(blue_key)
                    names = [f"v{idx}_{k}" for k in range(len(vals))]
                    placeholders.append("(" + ",".join(f":{n}" for n in names) + ")")
                    params.update(dict(zip(names, vals)))

                col_list = ",".join(cols)
                sql = text(
                    f"SELECT id, {col_list} FROM {table} "
                    f"WHERE ({col_list}) IN ({','.join(placeholders)})"
                )
                res = await db.execute(sql, params)
                found = set()
                for row in res.all():
                    vals = tuple(row[1:])  # 跳过 id
                    red_key = tuple(sorted(vals[:n_red]))
                    blue_key = tuple(sorted(vals[n_red:]))
                    key = (red_key, blue_key)
                    result_map[key] = row[0]
                    cache[key] = row[0]
                    cache.move_to_end(key)
                    found.add(key)
                # 未查到的组合也缓存 None，避免重复打 DB（静态表，缺失即永远缺失）
                for k in chunk:
                    if k not in found:
                        cache[k] = None
                        cache.move_to_end(k)

        # LRU 淘汰最久未用
        while len(cache) > _COMBO_ID_CACHE_MAX:
            cache.popitem(last=False)

    return result_map


# ==================== 今日预测综合分析（路由层薄封装调用此函数） ====================
def _lottery_info(rule, lottery_type):
    """构造彩种基础信息"""
    return {
        "name": rule['name'] if rule else lottery_type,
        "draw_days": rule['draw_days'] if rule else [],
        "draw_count": rule['draw_count'] if rule else 0,
    }


async def get_today_analysis_payload(lottery_type: str) -> dict:
    """
    组装当前开奖期预测分析的完整响应：预测记录（含相似度/全组合ID）、最优推荐、
    号码频率、开奖结果、期次信息。相似度只标记不剔除，全部预测参与统计。
    """
    target_date = get_target_draw_date(lottery_type)
    rule = LOTTERY_RULES.get(lottery_type)
    empty_base = {
        "forecasts": [], "recommendation": None, "result": None,
        "lottery_info": _lottery_info(rule, lottery_type),
        "upcoming": None, "target_draw_date": None, "frequency": None,
        "total": 0, "similarity_threshold": None, "similarity_threshold_value": None,
        "has_all_table_ids": False,
    }
    if target_date is None:
        return {**empty_base, "message": f"未找到 {lottery_type} 的下一个开奖日"}

    forecasts = await get_today_forecasts(lottery_type)
    if not forecasts:
        return {
            **empty_base,
            "message": f"当前开奖期（{target_date.strftime('%Y-%m-%d')}）暂无预测数据",
            "upcoming": await get_upcoming_draw_info(lottery_type),
            "target_draw_date": target_date.strftime("%Y-%m-%d"),
        }

    # 历史相似度（不剔除，全部保留；相似度信息回写 + 供展示）
    forecasts, _removed, sim_info, threshold = await filter_by_history_similarity(
        forecasts, lottery_type)

    recommendation = await analyze_best_recommendation(forecasts, lottery_type)
    frequency = await analyze_number_frequency(forecasts, lottery_type)
    latest_result = await get_today_latest_result(lottery_type)

    # 提取号码并批量查询全组合表 ID（空表内部短路）
    combos = [extract_forecast_numbers(lottery_type, f) for f in forecasts]
    id_map = await bulk_lookup_all_table_ids(lottery_type, combos)

    formatted_forecasts = []
    for f in forecasts:
        reds, blues = extract_forecast_numbers(lottery_type, f)
        red_key, blue_key = tuple(sorted(reds)), tuple(sorted(blues))
        sim = sim_info.get(f.model_version, {})
        formatted_forecasts.append({
            "red": reds,
            "blue": blues[0] if lottery_type == 'ssq' else blues,
            "quality_score": f.quality_score,
            "create_time": f.create_time.strftime("%Y-%m-%d %H:%M:%S") if f.create_time else None,
            "model_version": f.model_version,
            "all_table_id": id_map.get((red_key, blue_key)),
            "max_similarity": sim.get("max_similarity", 0),
            "matched_history_issue": sim.get("matched_history_issue"),
        })

    result_data = None
    if latest_result:
        d_reds, d_blues = extract_history_numbers(lottery_type, latest_result)
        result_data = {
            "red": d_reds,
            "blue": d_blues[0] if lottery_type == 'ssq' else d_blues,
            "issue_num": latest_result.issue_num,
            "draw_date": latest_result.draw_date.strftime("%Y-%m-%d") if latest_result.draw_date else None,
        }

    return {
        "forecasts": formatted_forecasts,
        "recommendation": recommendation,
        "result": result_data,
        "total": len(formatted_forecasts),
        "lottery_info": _lottery_info(rule, lottery_type),
        "upcoming": await get_upcoming_draw_info(lottery_type),
        "target_draw_date": target_date.strftime("%Y-%m-%d"),
        "frequency": frequency,
        "similarity_threshold": f"{threshold:.0%}",
        "similarity_threshold_value": threshold,
        "has_all_table_ids": bool(id_map),
    }