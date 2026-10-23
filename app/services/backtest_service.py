# -*- coding: utf-8 -*-
"""
回测服务：用历史数据逐期回测每个模型的真实命中率，写入 model_score 表。

自我学习闭环的评估基础：
- 对每个模型取最近 n_periods 期，逐期"只用该期之前的数据"预测，与真实开奖对比
- 所有期打包成一个 batch 一次前向（GPU 批处理），单个模型回测 <1 秒
- 命中率写入 model_score 表，供智能推荐与集成预测使用
"""
import json
import logging
import os
import time

import joblib
import numpy as np
import torch
from sqlalchemy import select, func

from app.core.config import settings
from app.core.database import SyncSessionLocal
from app.models.model_score import ModelScore
from .data_loader import (
    load_ssq_data_sync, load_dlt_data_sync, get_max_issue_sync,
    SSQ_FEATURE_COLS, SSQ_TARGET_COLS,
    DLT_FEATURE_COLS, DLT_TARGET_COLS,
    SSQ_RED_RANGE, SSQ_BLUE_RANGE,
    DLT_FRONT_RANGE, DLT_BACK_RANGE,
)
from .transformer_model import LotteryClassifier

logger = logging.getLogger(__name__)


def _load_lottery_config(lottery_type: str):
    """
    返回彩种对应的数据/维度配置元组。
    """
    if lottery_type == 'ssq':
        return (
            load_ssq_data_sync, SSQ_FEATURE_COLS, SSQ_TARGET_COLS,
            SSQ_RED_RANGE, SSQ_BLUE_RANGE, 33, 16, 6, 1,
        )
    return (
        load_dlt_data_sync, DLT_FEATURE_COLS, DLT_TARGET_COLS,
        DLT_FRONT_RANGE, DLT_BACK_RANGE, 35, 12, 5, 2,
    )


def _vectorized_hits(probs: np.ndarray, targets: np.ndarray,
                     num_red: int, red_pick: int, blue_pick: int):
    """
    向量化计算逐样本红/蓝命中率。
    """
    red_probs = probs[:, :num_red]
    blue_probs = probs[:, num_red:]
    true_red = targets[:, :num_red]
    true_blue = targets[:, num_red:]

    pred_red_idx = np.argsort(-red_probs, axis=1)[:, :red_pick]
    pred_blue_idx = np.argsort(-blue_probs, axis=1)[:, :blue_pick]
    pred_red_oh = np.zeros_like(red_probs, dtype=np.float32)
    pred_blue_oh = np.zeros_like(blue_probs, dtype=np.float32)
    np.put_along_axis(pred_red_oh, pred_red_idx, 1.0, axis=1)
    np.put_along_axis(pred_blue_oh, pred_blue_idx, 1.0, axis=1)

    red_hit = (pred_red_oh * true_red).sum(axis=1) / np.clip(true_red.sum(axis=1), 1, None)
    blue_hit = (pred_blue_oh * true_blue).sum(axis=1) / np.clip(true_blue.sum(axis=1), 1, None)
    return red_hit, blue_hit


# ---------- 随机基线：解析法 + 蒙特卡洛 ----------

_BASELINE_CONFIG = {
    # lottery_type: (N_red, K_red, red_pick, N_blue, K_blue, blue_pick)
    #   N=池大小, K=开出个数, pick=每期选几个
    "ssq": (33, 6, 6, 16, 1, 1),
    "dlt": (35, 5, 5, 12, 2, 2),
}


def baseline_expected_hits(lottery_type: str):
    """
    解析法计算随机选号的期望命中数与标准差（超几何分布）。

    返回 dict: {
        red: {E, SD, pct},
        blue: {E, SD, pct},
        total: {E, SD, pct},
    }
    pct = 命中率 (E / pick)
    """
    cfg = _BASELINE_CONFIG[lottery_type]
    N_r, K_r, n_r, N_b, K_b, n_b = cfg

    def _hgeom(N, K, n):
        E = n * K / N
        # 超几何方差：n * (K/N) * (1 - K/N) * (N-n)/(N-1)
        if N > 1:
            V = n * (K / N) * (1 - K / N) * (N - n) / (N - 1)
        else:
            V = 0.0
        SD = float(np.sqrt(max(V, 0)))
        pct = E / n if n > 0 else 0.0
        return {"E": float(E), "SD": SD, "pct": float(pct)}

    red = _hgeom(N_r, K_r, n_r)
    blue = _hgeom(N_b, K_b, n_b)
    total = {
        "E": red["E"] + blue["E"],
        "SD": float(np.sqrt(red["SD"] ** 2 + blue["SD"] ** 2)),
        "pct": (red["E"] + blue["E"]) / (n_r + n_b),
    }
    return {"red": red, "blue": blue, "total": total, "config": cfg}


def baseline_confidence(lottery_type: str, n_periods: int = 100, z: float = 1.96):
    """
    给定留出期数 M，计算 95% 置信阈值 = E + z * SE，
    模型平均命中数显著高于该阈值才算"超过随机"。
    """
    b = baseline_expected_hits(lottery_type)
    out = {}
    for seg in ("red", "blue", "total"):
        se = b[seg]["SD"] / np.sqrt(max(n_periods, 1))
        out[seg] = {
            "E": b[seg]["E"],
            "SD": b[seg]["SD"],
            "SE": float(se),
            "threshold_95": float(b[seg]["E"] + z * se),
        }
    out["n_periods"] = n_periods
    out["z"] = z
    return out


def baseline_montecarlo(lottery_type: str, n_trials: int = 100_000, seed: int = 42):
    """
    蒙特卡洛模拟随机选号的期望命中数，与解析法交叉验证。
    """
    cfg = _BASELINE_CONFIG[lottery_type]
    N_r, K_r, n_r, N_b, K_b, n_b = cfg
    rng = np.random.default_rng(seed)

    red_hits = np.empty(n_trials)
    blue_hits = np.empty(n_trials)
    for i in range(n_trials):
        red_hits[i] = len(rng.choice(N_r, n_r, replace=False)) if n_r <= N_r else n_r
        blue_hits[i] = len(rng.choice(N_b, n_b, replace=False)) if n_b <= N_b else n_b
    # 修正：不能直接数选到的，要模拟"选出的号码 vs 已知开奖号码"的交集
    # 正确做法：从 N 个里随机挑 K 个作为开奖，再挑 n 个作为预测，数交集
    red_hits_corr = np.empty(n_trials)
    blue_hits_corr = np.empty(n_trials)
    for i in range(n_trials):
        actual_r = set(rng.choice(N_r, K_r, replace=False).tolist())
        pred_r = set(rng.choice(N_r, n_r, replace=False).tolist())
        red_hits_corr[i] = len(actual_r & pred_r)
        actual_b = set(rng.choice(N_b, K_b, replace=False).tolist())
        pred_b = set(rng.choice(N_b, n_b, replace=False).tolist())
        blue_hits_corr[i] = len(actual_b & pred_b)

    return {
        "trials": n_trials,
        "seed": seed,
        "red_E": float(red_hits_corr.mean()),
        "red_SD": float(red_hits_corr.std()),
        "blue_E": float(blue_hits_corr.mean()),
        "blue_SD": float(blue_hits_corr.std()),
        "total_E": float(red_hits_corr.mean() + blue_hits_corr.mean()),
        "total_SD": float(np.sqrt(red_hits_corr.std()**2 + blue_hits_corr.std()**2)),
    }


def backtest_all_models(lottery_type: str, n_periods: int = None,
                        progress_cb=None, force: bool = False) -> dict:
    """
    回测指定彩种下所有模型，更新 model_score 表。
    n_periods 不传时取配置 BACKTEST_PERIODS。
    force=True 时强制重跑所有模型（默认跳过 model_score 已存在的，回测是确定性的）。

    严格样本外：每个模型只对 issue > meta.train_end_issue 的期打分，
    避免模型"见过"的数据泄漏。
    """
    (load_fn, feature_cols, target_cols, num_red, num_blue,
     red_upper, blue_upper, red_pick, blue_pick) = _load_lottery_config(lottery_type)

    df = load_fn()
    if df is None or len(df) < 60:
        raise ValueError(f"数据不足无法回测，当前 {len(df) if df is not None else 0} 条")

    n_periods = n_periods or settings.BACKTEST_PERIODS
    n_periods = max(1, min(n_periods, len(df) - 30))
    feature_dim = len(feature_cols)
    total = len(df)

    # ---- 严格样本外：latest_issue - total + 1 = df 首行对应的期号 ----
    latest_issue = get_max_issue_sync(lottery_type)
    first_issue = latest_issue - total + 1
    logger.info(f"📊 回测：df 首行期号 {first_issue}、末行期号 {latest_issue}，共 {total} 行")

    # 每期 t 的输入窗口 = rows[t-seq_len:t]（严格早于该期），目标 = rows[t] 的 multi-hot
    model_dir = os.path.join(settings.MODEL_SAVE_DIR, lottery_type)
    model_files = sorted(
        f for f in os.listdir(model_dir)
        if f.endswith('.pt') and not f.endswith('_final.pt')
    )
    if not model_files:
        raise ValueError(f"{lottery_type} 无可回测模型")

    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    # ---- 预查 model_score：已打分的模型直接跳过（回测是确定性的，历史数据不变则打分不变） ----
    existing_scores = set()
    with SyncSessionLocal() as _pre:
        _rows = _pre.execute(
            select(ModelScore.model_name).where(ModelScore.lottery_type == lottery_type)
        ).scalars().all()
        existing_scores = set(_rows)

    done = 0
    results = []
    score_rows = []   # 收集 (model_name, hit_red, hit_blue, hit_total, periods)，循环后批量写
    for model_file in model_files:
        run_id = os.path.splitext(model_file)[0]

        # 已有评分记录 → 跳过（force=True 可强制重跑）
        if model_file in existing_scores and not force:
            done += 1
            continue

        meta_path = os.path.join(model_dir, f"{run_id}_meta.json")
        scaler_path = os.path.join(model_dir, f"{run_id}_scaler.joblib")
        if not (os.path.exists(meta_path) and os.path.exists(scaler_path)):
            done += 1
            continue

        model = None
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            if meta.get("model_type") != "classifier":
                done += 1
                continue

            seq_len = int(meta.get("pred_seq_len", 30))

            # ---- 严格样本外：只对 train_end_issue 之后的期打分 ----
            train_end_issue = int(meta.get("train_end_issue", 0))
            direction = meta.get("direction", "forward")

            # train_cut = 训练数据最后一行在 df 中的索引
            # 行号 = issue - first_issue
            train_cut = max(0, train_end_issue - first_issue)

            # 回测期 t 必须满足：输入窗口 AND 目标行都严格在 train_cut 之后
            if direction == 'forward':
                # 输入 rows[t-seq_len:t] + 目标 row[t] 全部要 > train_cut
                # t-seq_len > train_cut ⇒ t >= train_cut + 1 + seq_len
                min_t = seq_len + train_cut + 1
            else:  # backward
                # 输入 rows[t+1 : t+1+seq_len] + 目标 row[t] 全部要 > train_cut
                # t+1 > train_cut 且 t > train_cut ⇒ t >= train_cut + 1
                min_t = train_cut + 1

            if min_t >= total:
                # 无可用的严格样本外期（模型训练后没有新数据），跳过
                done += 1
                continue

            # 最多回测 n_periods 期，但不超过剩余期数
            max_t_end = total
            requested_end = min_t + n_periods
            t_end = min(max_t_end, requested_end)
            t_start = min_t
            periods = t_end - t_start

            if periods <= 0:
                done += 1
                continue

            # 打包所有回测期窗口为一个 batch
            windows, targets = [], []
            for t in range(t_start, t_end):
                if direction == 'forward':
                    windows.append(df.values[t - seq_len:t])
                    targets.append(df[target_cols].values[t])
                else:
                    # backward: 模型训练时 input=rows[t+1:t+1+seq_len], target=row[t]
                    windows.append(df.values[t + 1:t + 1 + seq_len])
                    targets.append(df[target_cols].values[t])
            batch = np.array(windows, dtype=np.float32)
            targets = np.array(targets, dtype=np.float32)

            scaler = joblib.load(scaler_path)
            scaled_feats = scaler.transform(batch[:, :, :feature_dim].reshape(-1, feature_dim))
            scaled_feats = scaled_feats.reshape(batch.shape[0], batch.shape[1], feature_dim)
            batch = np.concatenate([scaled_feats, batch[:, :, feature_dim:]], axis=2)

            model = LotteryClassifier(
                input_dim=meta.get("input_dim", feature_dim + len(target_cols)),
                d_model=meta.get("d_model", 64),
                nhead=meta.get("nhead", 4),
                num_layers=meta.get("num_layers", 2),
                num_red=num_red,
                num_blue=num_blue,
                dropout=meta.get("dropout", 0.3),
            )
            state = torch.load(os.path.join(model_dir, model_file),
                               map_location='cpu', weights_only=False)
            model.load_state_dict(state)
            model.to(device).eval()

            x = torch.tensor(batch, dtype=torch.float32, device=device)
            with torch.no_grad(), torch.autocast(
                    device_type='cuda', dtype=torch.float16, enabled=device.type == 'cuda'):
                logits = model(x).float().cpu().numpy()
            probs = 1.0 / (1.0 + np.exp(-logits))

            red_hit, blue_hit = _vectorized_hits(probs, targets, num_red, red_pick, blue_pick)
            hit_red = float(red_hit.mean())
            hit_blue = float(blue_hit.mean())
            # 按各彩种号码个数加权（ssq 红6蓝1 / dlt 前5后2），避免蓝球仅1个号却占50%权重
            hit_total = (hit_red * red_pick + hit_blue * blue_pick) / (red_pick + blue_pick)

            score_rows.append((model_file, hit_red, hit_blue, hit_total, periods))
            results.append({
                "model_name": model_file, "hit_red": round(hit_red, 4),
                "hit_blue": round(hit_blue, 4), "hit_total": round(hit_total, 4),
                "periods": periods,
            })
        except Exception as e:
            results.append({"model_name": model_file, "error": str(e)})
        finally:
            # 显式释放该模型 GPU 资源，避免数千模型累积显存碎片
            del model
            if device.type == 'cuda' and done % 50 == 0:
                torch.cuda.empty_cache()
            done += 1
            if progress_cb:
                progress_cb(done, len(model_files))

    # 所有模型评分完成后：单会话批量入库 + 归还 GPU 缓存
    _bulk_upsert_scores(lottery_type, score_rows)
    if device.type == 'cuda':
        torch.cuda.empty_cache()

    return {"total": len(model_files), "scored": len(results), "results": results}


def _bulk_upsert_scores(lottery_type: str, score_rows: list):
    """
    批量写入/更新 model_score：一次 IN 查询已存在记录，内存匹配后单次 commit。
    score_rows: [(model_name, hit_red, hit_blue, hit_total, periods), ...]
    """
    if not score_rows:
        return
    names = [r[0] for r in score_rows]
    with SyncSessionLocal() as session:
        existing = {
            s.model_name: s for s in session.execute(
                select(ModelScore).where(
                    ModelScore.lottery_type == lottery_type,
                    ModelScore.model_name.in_(names))
            ).scalars().all()
        }
        for model_name, hit_red, hit_blue, hit_total, periods in score_rows:
            score = existing.get(model_name)
            if score is None:
                score = ModelScore(lottery_type=lottery_type, model_name=model_name)
                session.add(score)
            score.hit_red = hit_red
            score.hit_blue = hit_blue
            score.hit_total = hit_total
            score.evaluated_periods = periods
        session.commit()


def get_leaderboard(lottery_type: str, page: int = 1, page_size: int = 10) -> dict:
    """
    返回按综合命中率降序的模型榜单（服务端分页）。
    数据量大（数千模型）时只取当前页 + 一次 COUNT，避免全量拉取/序列化/传输。
    返回 {"leaderboard": 当前页行, "total": 总行数, "page": 页码, "page_size": 每页条数}。
    """
    page = max(1, page)
    page_size = min(max(page_size, 1), 100)

    with SyncSessionLocal() as session:
        total = session.execute(
            select(func.count()).select_from(ModelScore)
            .where(ModelScore.lottery_type == lottery_type)
        ).scalar_one()
        rows = session.execute(
            select(ModelScore)
            .where(ModelScore.lottery_type == lottery_type)
            .order_by(ModelScore.hit_total.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).scalars().all()
        items = [
            {
                "model_name": r.model_name,
                "hit_red": round(r.hit_red, 4),
                "hit_blue": round(r.hit_blue, 4),
                "hit_total": round(r.hit_total, 4),
                "evaluated_periods": r.evaluated_periods,
                "updated_at": r.updated_at.strftime("%Y-%m-%d %H:%M") if r.updated_at else None,
            }
            for r in rows
        ]

    return {
        "leaderboard": items,
        "total": total,
        "page": page,
        "page_size": page_size
    }


def get_top_models(lottery_type: str, top_k: int = 5) -> list:
    """
    返回回测命中率最高的 K 个模型名（自我学习反馈入口）。
    """
    with SyncSessionLocal() as session:
        stmt = select(ModelScore).where(
            ModelScore.lottery_type == lottery_type,
        ).order_by(ModelScore.hit_total.desc()).limit(top_k)
        rows = session.execute(stmt).scalars().all()
        return [r.model_name for r in rows]


# 困难期次缓存：{lottery_type: (timestamp, set_of_df_rows)}，1 小时失效
_HARD_PERIODS_CACHE = {}


def get_hard_periods(lottery_type: str, top_k: int = 5, n_periods: int = None,
                     threshold: float = 0.3) -> set:
    """
    返回困难期次在 df 中的行号集合（供 trainer 训练时对错误样本加权）。

    困难定义：Top-K 模型在可用期次上的平均综合命中率 < threshold 的期次。
    n_periods 不传时回测所有可用期次（计算量大，但结果缓存 1 小时）。
    每个模型按各自 seq_len 构建窗口，period_hits 按期次 df 行号聚合。
    """
    import time as _time
    cached = _HARD_PERIODS_CACHE.get(lottery_type)
    if cached and (_time.time() - cached[0] < 3600):
        return cached[1]

    (load_fn, feature_cols, target_cols, num_red, num_blue,
     red_upper, blue_upper, red_pick, blue_pick) = _load_lottery_config(lottery_type)

    df = load_fn()
    if df is None or len(df) < 60:
        return set()

    total = len(df)
    feature_dim = len(feature_cols)

    # 从 model_score 表取 Top-K 模型
    top_model_names = get_top_models(lottery_type, top_k=top_k)
    if not top_model_names:
        return set()

    model_dir = os.path.join(settings.MODEL_SAVE_DIR, lottery_type)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    # 收集每个期次的 Top-K 综合命中率
    period_hits = {}  # {df_row: [hit_model_0, ...]}

    for model_name in top_model_names:
        # model_name 形如 "ssq_..._1234567890.pt"，确保带 .pt 后缀
        if not model_name.endswith('.pt'):
            model_name = model_name + '.pt'
        run_id = os.path.splitext(model_name)[0]
        model_path = os.path.join(model_dir, model_name)
        meta_path = os.path.join(model_dir, f"{run_id}_meta.json")
        scaler_path = os.path.join(model_dir, f"{run_id}_scaler.joblib")
        if not (os.path.exists(model_path) and os.path.exists(meta_path)
                and os.path.exists(scaler_path)):
            continue

        model = None
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            if meta.get("model_type") != "classifier":
                continue
            seq_len = int(meta.get("pred_seq_len", 30))

            # 回测范围：最近 n_periods 期，不传则回测所有可用期次
            if n_periods is None:
                periods = max(1, total - seq_len - 1)
            else:
                periods = max(1, min(n_periods, total - seq_len - 1))

            period_rows = list(range(total - periods, total))
            windows, targets = [], []
            for t in period_rows:
                windows.append(df.values[t - seq_len:t])
                targets.append(df[target_cols].values[t])
            batch = np.array(windows, dtype=np.float32)
            targets = np.array(targets, dtype=np.float32)

            scaler = joblib.load(scaler_path)
            scaled_feats = scaler.transform(
                batch[:, :, :feature_dim].reshape(-1, feature_dim))
            scaled_feats = scaled_feats.reshape(
                batch.shape[0], batch.shape[1], feature_dim)
            batch = np.concatenate([scaled_feats, batch[:, :, feature_dim:]], axis=2)

            model = LotteryClassifier(
                input_dim=meta.get("input_dim", feature_dim + len(target_cols)),
                d_model=meta.get("d_model", 64),
                nhead=meta.get("nhead", 4),
                num_layers=meta.get("num_layers", 2),
                num_red=num_red, num_blue=num_blue,
                dropout=meta.get("dropout", 0.3),
            )
            state = torch.load(model_path, map_location='cpu', weights_only=False)
            model.load_state_dict(state)
            model.to(device).eval()

            x = torch.tensor(batch, dtype=torch.float32, device=device)
            with torch.no_grad(), torch.autocast(
                    device_type='cuda', dtype=torch.float16,
                    enabled=device.type == 'cuda'):
                logits = model(x).float().cpu().numpy()
            probs = 1.0 / (1.0 + np.exp(-logits))

            red_hit, blue_hit = _vectorized_hits(
                probs, targets, num_red, red_pick, blue_pick)
            hit_total = (red_hit * red_pick + blue_hit * blue_pick) / (red_pick + blue_pick)

            for i, t in enumerate(period_rows):
                period_hits.setdefault(t, []).append(float(hit_total[i]))
        except Exception:
            continue
        finally:
            del model
            if device.type == 'cuda':
                torch.cuda.empty_cache()

    # 每期 Top-K 平均命中率 < threshold 标记为困难
    hard_periods = set()
    for t, hits in period_hits.items():
        if hits and (sum(hits) / len(hits)) < threshold:
            hard_periods.add(t)

    _HARD_PERIODS_CACHE[lottery_type] = (_time.time(), hard_periods)
    if device.type == 'cuda':
        torch.cuda.empty_cache()
    return hard_periods


# 高命中率超参区间缓存：{lottery_type: (timestamp, params_dict)}
_TOP_HYPERPARAMS_CACHE = {}


def get_top_hyperparams(lottery_type: str, top_k: int = 20) -> dict:
    """
    统计高命中率模型的超参分布，供新训练偏向采样（P2 超参元学习）。

    返回：
        {
            "epochs_range": (low, high),   # 中位数 ± 20%（整数边界）
            "batch_sizes": [bs1, bs2],     # 频次最高的前 2 个
            "lr_log_range": (low, high),   # 10^(对数均值±0.5)
        }
    无 Top-K 模型或 meta 缺失时返回空 dict，调用方应回退到全随机。
    结果缓存 1 小时。
    """
    import math as _math
    import statistics
    import time as _time
    from collections import Counter

    cached = _TOP_HYPERPARAMS_CACHE.get(lottery_type)
    if cached and (_time.time() - cached[0] < 3600):
        return cached[1]

    top_model_names = get_top_models(lottery_type, top_k=top_k)
    if not top_model_names:
        return {}

    model_dir = os.path.join(settings.MODEL_SAVE_DIR, lottery_type)
    epochs_list, batch_sizes_list, lr_logs = [], [], []
    for model_name in top_model_names:
        if not model_name.endswith('.pt'):
            model_name = model_name + '.pt'
        run_id = os.path.splitext(model_name)[0]
        meta_path = os.path.join(model_dir, f"{run_id}_meta.json")
        if not os.path.exists(meta_path):
            continue
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            ep = int(meta.get("epochs", 0))
            bs = int(meta.get("batch_size", 0))
            lr = float(meta.get("learning_rate", 0))
            if ep > 0 and bs > 0 and lr > 0:
                epochs_list.append(ep)
                batch_sizes_list.append(bs)
                lr_logs.append(_math.log10(lr))
        except Exception:
            continue

    if not epochs_list:
        return {}

    # epochs：中位数 ± 20%，整数边界
    ep_median = statistics.median(epochs_list)
    ep_low = max(1, int(ep_median * 0.8))
    ep_high = int(ep_median * 1.2)
    if ep_low > ep_high:
        ep_low, ep_high = ep_high, ep_low

    # batch_size：频次最高的前 2 个
    bs_top = [bs for bs, _ in Counter(batch_sizes_list).most_common(2)]

    # lr：对数空间均值 ± 0.5
    lr_mean = statistics.mean(lr_logs)
    lr_low = 10 ** (lr_mean - 0.5)
    lr_high = 10 ** (lr_mean + 0.5)
    if lr_low > lr_high:
        lr_low, lr_high = lr_high, lr_low

    result = {
        "epochs_range": (ep_low, ep_high),
        "batch_sizes": bs_top,
        "lr_log_range": (lr_low, lr_high),
    }
    _TOP_HYPERPARAMS_CACHE[lottery_type] = (_time.time(), result)
    return result


def sample_recommended_params(lottery_type: str) -> dict | None:
    """
    从高命中率模型的超参区间中采样一组具体训练参数（P2 超参元学习）。
    复用 get_top_hyperparams 的缓存结果。
    无 Top-K 模型数据时返回 None，调用方回退到请求默认值。
    """
    import math
    import random

    hp = get_top_hyperparams(lottery_type)
    if not hp:
        return None

    # epochs: 从中位区间均匀采样
    ep_low, ep_high = hp["epochs_range"]
    epochs = random.randint(min(ep_low, ep_high), max(ep_low, ep_high))

    # batch_size: 从频次最高的候选中随机选
    batch_size = random.choice(hp["batch_sizes"])

    # learning_rate: 对数空间均匀采样
    lr_low, lr_high = hp["lr_log_range"]
    learning_rate = 10 ** random.uniform(
        math.log10(lr_low), math.log10(lr_high))

    return {
        "epochs": epochs,
        "batch_size": batch_size,
        "learning_rate": round(learning_rate, 8),
    }


# 弱点号码缓存：{lottery_type: (timestamp, {"red": set, "blue": set})}，1 小时失效
_WEAK_NUMBERS_CACHE = {}


def get_weak_numbers(lottery_type: str, top_k: int = 5, n_periods: int = 50,
                     threshold: float = 0.7) -> dict:
    """
    返回经常被漏掉的号码集合（供 trainer 训练时对这些号码 loss 加权，P3 弱点强化）。

    弱点定义：真实出现该号码的期次中，Top-K 模型漏掉的比例 > threshold。
    返回 {"red": set(号码索引), "blue": set(号码索引)}（0-based 索引）。
    无 Top-K 模型时返回空集合。结果缓存 1 小时。
    """
    import time as _time
    cached = _WEAK_NUMBERS_CACHE.get(lottery_type)
    if cached and (_time.time() - cached[0] < 3600):
        return cached[1]

    (load_fn, feature_cols, target_cols, num_red, num_blue,
     red_upper, blue_upper, red_pick, blue_pick) = _load_lottery_config(lottery_type)

    df = load_fn()
    if df is None or len(df) < 60:
        return {"red": set(), "blue": set()}

    total = len(df)
    feature_dim = len(feature_cols)

    top_model_names = get_top_models(lottery_type, top_k=top_k)
    if not top_model_names:
        return {"red": set(), "blue": set()}

    model_dir = os.path.join(settings.MODEL_SAVE_DIR, lottery_type)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

    # miss[n] = 该号码被漏掉的总次数（跨所有模型和期次）
    red_miss = np.zeros(num_red, dtype=np.float32)
    blue_miss = np.zeros(num_blue, dtype=np.float32)
    # appear[n] = 该号码在真实开奖中出现的次数（所有期次，不乘 K）
    red_appear = np.zeros(num_red, dtype=np.float32)
    blue_appear = np.zeros(num_blue, dtype=np.float32)
    K = 0  # 实际参与统计的模型数

    for model_name in top_model_names:
        if not model_name.endswith('.pt'):
            model_name = model_name + '.pt'
        run_id = os.path.splitext(model_name)[0]
        model_path = os.path.join(model_dir, model_name)
        meta_path = os.path.join(model_dir, f"{run_id}_meta.json")
        scaler_path = os.path.join(model_dir, f"{run_id}_scaler.joblib")
        if not (os.path.exists(model_path) and os.path.exists(meta_path)
                and os.path.exists(scaler_path)):
            continue

        model = None
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            if meta.get("model_type") != "classifier":
                continue
            seq_len = int(meta.get("pred_seq_len", 30))
            periods = max(1, min(n_periods, total - seq_len - 1))

            period_rows = list(range(total - periods, total))
            windows, targets = [], []
            for t in period_rows:
                windows.append(df.values[t - seq_len:t])
                targets.append(df[target_cols].values[t])
            batch = np.array(windows, dtype=np.float32)
            targets = np.array(targets, dtype=np.float32)

            scaler = joblib.load(scaler_path)
            scaled_feats = scaler.transform(
                batch[:, :, :feature_dim].reshape(-1, feature_dim))
            scaled_feats = scaled_feats.reshape(
                batch.shape[0], batch.shape[1], feature_dim)
            batch = np.concatenate([scaled_feats, batch[:, :, feature_dim:]], axis=2)

            model = LotteryClassifier(
                input_dim=meta.get("input_dim", feature_dim + len(target_cols)),
                d_model=meta.get("d_model", 64),
                nhead=meta.get("nhead", 4),
                num_layers=meta.get("num_layers", 2),
                num_red=num_red, num_blue=num_blue,
                dropout=meta.get("dropout", 0.3),
            )
            state = torch.load(model_path, map_location='cpu', weights_only=False)
            model.load_state_dict(state)
            model.to(device).eval()

            x = torch.tensor(batch, dtype=torch.float32, device=device)
            with torch.no_grad(), torch.autocast(
                    device_type='cuda', dtype=torch.float16,
                    enabled=device.type == 'cuda'):
                logits = model(x).float().cpu().numpy()
            probs = 1.0 / (1.0 + np.exp(-logits))

            # 预测的 Top-K 号码 one-hot
            red_probs = probs[:, :num_red]
            blue_probs = probs[:, num_red:]
            pred_red_idx = np.argsort(-red_probs, axis=1)[:, :red_pick]
            pred_blue_idx = np.argsort(-blue_probs, axis=1)[:, :blue_pick]
            pred_red_oh = np.zeros_like(red_probs, dtype=np.float32)
            pred_blue_oh = np.zeros_like(blue_probs, dtype=np.float32)
            np.put_along_axis(pred_red_oh, pred_red_idx, 1.0, axis=1)
            np.put_along_axis(pred_blue_oh, pred_blue_idx, 1.0, axis=1)

            true_red = targets[:, :num_red]
            true_blue = targets[:, num_red:]

            # 漏球：真实出现但未预测
            red_miss += (true_red * (1 - pred_red_oh)).sum(axis=0)
            blue_miss += (true_blue * (1 - pred_blue_oh)).sum(axis=0)
            # appear 只累加一次（真实开奖固定，每模型相同）
            if K == 0:
                red_appear += true_red.sum(axis=0)
                blue_appear += true_blue.sum(axis=0)
            K += 1
        except Exception:
            continue
        finally:
            del model
            if device.type == 'cuda':
                torch.cuda.empty_cache()

    if K == 0:
        return {"red": set(), "blue": set()}

    # 漏球率 = miss / (appear * K)
    red_miss_rate = red_miss / np.clip(red_appear * K, 1, None)
    blue_miss_rate = blue_miss / np.clip(blue_appear * K, 1, None)

    red_weak = set(np.where(red_miss_rate > threshold)[0].tolist())
    blue_weak = set(np.where(blue_miss_rate > threshold)[0].tolist())

    result = {"red": red_weak, "blue": blue_weak}
    _WEAK_NUMBERS_CACHE[lottery_type] = (_time.time(), result)
    if device.type == 'cuda':
        torch.cuda.empty_cache()
    return result
