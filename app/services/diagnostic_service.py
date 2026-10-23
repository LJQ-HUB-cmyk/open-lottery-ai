# -*- coding: utf-8 -*-
"""
诊断服务：随机基线 + 双向评估 + 一致性判定。

核心输出：
  - 随机基线（解析法 + 蒙特卡洛交叉验证）
  - 每个模型的严格样本外命中率（train_end_issue 过滤后）
  - 相对基线的 lift + 95% 置信区间
  - 双向一致性判定（正向 & 反向都显著 > 0 才算"有信号"）

诚实预期：绝大多数情况下 lift 的置信区间会跨过 0，
对应结论 = "无可靠信号"（模型历史吻合度 = 纯随机水平）。
"""
import json
import logging
import os

import numpy as np

from app.core.config import settings
from app.services.data_loader import get_max_issue_sync
from .backtest_service import (
    backtest_all_models, get_top_models, get_top_hyperparams,
    baseline_expected_hits, baseline_confidence, baseline_montecarlo, _BASELINE_CONFIG,
)

logger = logging.getLogger(__name__)

# ---------- 进程内缓存 ----------
# 基线 / 蒙特卡洛：只依赖彩种 + n_periods，永久缓存（不依赖历史数据）
_BASELINE_CACHE = {}  # (lottery, n_periods, z) -> (baseline, confidence, mc)

# 完整报告缓存：key=(lottery, latest_issue, top_k, z)，value=(report, model_dir_mtime)
# latest_issue 变 → 历史数据更新 → 失效；模型目录 mtime 变 → 模型重训练 → 失效
_REPORT_CACHE = {}
_REPORT_CACHE_MAX = 32


def _get_model_dir_mtime(lottery_type: str) -> float:
    model_dir = os.path.join(settings.MODEL_SAVE_DIR, lottery_type)
    if not os.path.isdir(model_dir):
        return 0.0
    # 取最新修改的模型文件的 mtime
    mtime = 0.0
    for f in os.listdir(model_dir):
        if f.endswith('.pt') and not f.endswith('_final.pt'):
            try:
                mt = os.path.getmtime(os.path.join(model_dir, f))
                if mt > mtime:
                    mtime = mt
            except OSError:
                pass
    return mtime


# ---------- 置信区间计算 ----------

def _binomial_ci(mean_hit: float, baseline_E: float, sd: float,
                 n_periods: int, z: float = 1.96):
    """
    计算 lift = mean_hit - baseline_E 的近似 95% 置信区间。

    参数:
        mean_hit: 模型在样本外的平均命中数
        baseline_E: 随机基线期望命中数
        sd: 模型命中数的标准差（若拿不到则用基线 SD）
        n_periods: 留出期数
        z: 正态分位点（1.96 ≈ 95%）
    返回:
        dict: {mean, baseline_E, lift, ci_low, ci_high, significant}
    """
    if n_periods <= 0:
        return {"mean": mean_hit, "baseline_E": baseline_E, "lift": float("nan"),
                "ci_low": float("nan"), "ci_high": float("nan"), "significant": None}

    se_hit = sd / np.sqrt(n_periods)
    se_baseline = 0.0  # 基线是已知常数，无不确定性
    se = float(np.sqrt(se_hit ** 2 + se_baseline ** 2))

    lift = mean_hit - baseline_E
    ci_low = lift - z * se
    ci_high = lift + z * se
    significant = ci_low > 0  # 置信下界严格 > 0 才算显著

    return {
        "mean": float(mean_hit),
        "baseline_E": float(baseline_E),
        "lift": float(lift),
        "ci_low": float(ci_low),
        "ci_high": float(ci_high),
        "SE": se,
        "z": z,
        "n_periods": n_periods,
        "significant": bool(significant),
    }


# ---------- 模型方向分组 ----------

def _group_models_by_direction(lottery_type: str, model_files=None):
    """
    扫描模型目录，按 direction=forward / backward 分组。
    缺失 direction 的旧模型默认归为 forward。
    返回: {"forward": [{"run_id", "train_end_issue", ...}], "backward": [...]}
    """
    model_dir = os.path.join(settings.MODEL_SAVE_DIR, lottery_type)
    if not os.path.isdir(model_dir):
        return {"forward": [], "backward": []}

    if model_files is None:
        model_files = [f for f in os.listdir(model_dir)
                       if f.endswith('.pt') and not f.endswith('_final.pt')]

    groups = {"forward": [], "backward": []}
    for mf in model_files:
        run_id = os.path.splitext(mf)[0]
        meta_path = os.path.join(model_dir, f"{run_id}_meta.json")
        if not os.path.exists(meta_path):
            groups["forward"].append({"run_id": run_id, "train_end_issue": 0,
                                      "direction": "forward"})
            continue
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
        except Exception:
            continue
        direction = meta.get("direction", "forward")
        groups.setdefault(direction, []).append({
            "run_id": run_id,
            "train_end_issue": meta.get("train_end_issue", 0),
            "direction": direction,
            "best_hit_rate": meta.get("best_hit_rate"),
            "trained_at": meta.get("trained_at"),
        })
    return groups


# ---------- 主诊断入口 ----------

def run_diagnostic(lottery_type: str, n_periods: int = None,
                   top_k: int = 5, z: float = 1.96) -> dict:
    """
    完整诊断报告。

    Args:
        lottery_type: 'ssq' 或 'dlt'
        n_periods: 回测期数（不传取配置）
        top_k: 报告 Top-K 模型详细信息
        z: 置信水平 z 值（1.96=95%）

    Returns:
        dict: 基线信息、各方向模型列表、双向一致性判定、总体结论
    """
    assert lottery_type in ('ssq', 'dlt')
    n_periods = n_periods or settings.BACKTEST_PERIODS
    latest_issue = get_max_issue_sync(lottery_type)
    mdir_mtime = _get_model_dir_mtime(lottery_type)

    # ---- 完整报告缓存命中 → 直接返回 ----
    report_key = (lottery_type, latest_issue, top_k, z)
    cached = _REPORT_CACHE.get(report_key)
    if cached is not None and cached[1] == mdir_mtime:
        logger.info("诊断缓存命中 %s issue=%s", lottery_type, latest_issue)
        return cached[0]

    # ---- baseline / 蒙特卡洛缓存 ----
    bkey = (lottery_type, n_periods, z)
    if bkey in _BASELINE_CACHE:
        baseline, confidence, mc = _BASELINE_CACHE[bkey]
    else:
        baseline = baseline_expected_hits(lottery_type)
        confidence = baseline_confidence(lottery_type, n_periods=n_periods, z=z)
        mc = baseline_montecarlo(lottery_type, n_trials=20_000)
        _BASELINE_CACHE[bkey] = (baseline, confidence, mc)

    report = {
        "lottery_type": lottery_type,
        "generated_at": latest_issue,
        "n_periods": n_periods,
        "latest_issue": latest_issue,
        "baseline": {
            "analytical": baseline,
            "confidence": confidence,
            "montecarlo_20k": mc,
        },
        "model_groups": {},
        "consistency_check": None,
        "conclusion": None,
    }

    # 2. 分组模型文件（只列，不回测）
    groups = _group_models_by_direction(lottery_type)
    for d in ("forward", "backward"):
        report["model_groups"][d] = {
            "count": len(groups[d]),
            "latest": groups[d][-3:] if groups[d] else [],
        }

    # 如果两边都没有模型，直接返回基础报告
    if not groups["forward"] and not groups["backward"]:
        report["conclusion"] = {
            "status": "NO_MODELS",
            "message": f"{lottery_type} 下无可用模型，先跑训练。",
        }
        return report

    # 3. 跑回测（forward + backward 都回测，model_score 表里 direction 字段可区分）
    try:
        backtest_all_models(lottery_type, n_periods=n_periods)
    except Exception as e:
        logger.exception("回测失败：%s", e)
        report["conclusion"] = {"status": "BACKTEST_FAILED", "message": str(e)}
        return report

    # 4. 从 model_score 取 Top-K 已评分模型，计算 lift
    #    按 model_name 前缀 dirforward / dirbackward 分组（无前缀归为 forward，向后兼容）
    from app.core.database import SyncSessionLocal
    from app.models.model_score import ModelScore

    def _score_direction(model_name: str) -> str:
        if "dirbackward" in model_name:
            return "backward"
        return "forward"  # dirforward 或无前缀 → forward

    # 收集所有模型的 meta（train_end_issue 等）供后续使用
    all_metas = {}
    for d in ("forward", "backward"):
        for m in groups[d]:
            all_metas[m["run_id"] + ".pt"] = m   # model_score 存带 .pt 后缀

    direction_evals = {}
    for direction in ("forward", "backward"):
        direction_results = []
        with SyncSessionLocal() as session:
            # 先取全部该方向有评分的行（按 hit_total 降序）
            all_scored = session.query(ModelScore).filter_by(
                lottery_type=lottery_type,
            ).all()
            # 内存过滤：按 model_name 判断方向 + 按 hit_total 排序
            filtered = [s for s in all_scored if _score_direction(s.model_name) == direction]
            filtered.sort(key=lambda s: s.hit_total or 0, reverse=True)
            top_rows = filtered[:top_k]

            for row in top_rows:
                periods = row.evaluated_periods or 0
                # hit_total 是所有期加权平均的每期命中个数（backtest 里是 mean()，已加权红蓝）
                # baseline E 是期望命中个数/期 —— 量纲一致，直接相减 = lift
                mean_hit = row.hit_total or 0.0
                baseline_E = baseline["total"]["E"]
                baseline_SD = baseline["total"]["SD"]

                meta = all_metas.get(row.model_name, {})
                lift_info = _binomial_ci(mean_hit, baseline_E, baseline_SD, periods, z=z)
                direction_results.append({
                    "run_id": row.model_name.replace(".pt", ""),
                    "model_name": row.model_name,
                    "train_end_issue": meta.get("train_end_issue", 0),
                    "mean_hit_per_period": mean_hit,
                    "hit_total": row.hit_total,
                    "hit_red": row.hit_red,
                    "hit_blue": row.hit_blue,
                    "baseline_E": baseline_E,
                    "periods_evaluated": periods,
                    "evaluated_period": None,
                    "lift_ci": lift_info,
                })
        direction_evals[direction] = direction_results

    report["direction_evals"] = direction_evals

    # 5. 双向一致性判定
    forward_sig = any(r["lift_ci"]["significant"] for r in (direction_evals.get("forward") or []))
    backward_sig = any(r["lift_ci"]["significant"] for r in (direction_evals.get("backward") or []))

    consistency = {
        "forward_any_significant": forward_sig,
        "backward_any_significant": backward_sig,
        "consistent_both": forward_sig and backward_sig,
        "consistent_neither": (not forward_sig) and (not backward_sig),
        "intermediate": bool(forward_sig != backward_sig),  # 只有一边显著，理论上不可逆，视为异常
    }
    report["consistency_check"] = consistency

    if consistency["consistent_both"]:
        conclusion_status = "SIGNAL_DETECTED"
        conclusion_msg = (
            "双向都存在显著高于随机基线的模型 — 理论上存在可外推信号，"
            "但建议重复多轮留出期评估交叉验证。"
        )
    elif consistency["consistent_neither"]:
        conclusion_status = "NO_SIGNAL"
        conclusion_msg = (
            "双向都未观测到显著高于随机基线的模型 — 当前所有模型的样本外表现 = 纯随机水平，"
            "建议停止在噪音上过拟合，接受无信号结论。"
        )
    else:
        conclusion_status = "INCONSISTENT"
        conclusion_msg = (
            "只有单方向存在显著模型，理论上不可能 — 可能是数据泄漏、回测错误或单方向噪声偶然抬升，"
            "建议先检查模型的 train_end_issue 是否正确。"
        )

    report["conclusion"] = {
        "status": conclusion_status,
        "message": conclusion_msg,
        "interpretation": (
            "置信下界严格 > 0 才视为显著。"
            f"随机基线期望 {baseline['total']['E']:.3f} 个/期 ± {baseline['total']['SD']:.3f} SD。"
            f"95% 阈值 = {confidence['total']['threshold_95']:.3f} 个/期。"
        ),
    }

    logger.info("✅ 诊断完成 %s: %s", lottery_type, conclusion_status)

    # 写入完整报告缓存（有界保护）
    _REPORT_CACHE[report_key] = (report, mdir_mtime)
    if len(_REPORT_CACHE) > _REPORT_CACHE_MAX:
        _REPORT_CACHE.clear()
        _REPORT_CACHE[report_key] = (report, mdir_mtime)

    return report


def quick_diagnostic(lottery_type: str) -> str:
    """
    精简版诊断（打印到日志 / 控制台的一句话结论）。
    """
    report = run_diagnostic(lottery_type)
    conc = report["conclusion"]
    base = report["baseline"]["confidence"]["total"]
    forward_count = report["model_groups"]["forward"]["count"]
    backward_count = report["model_groups"]["backward"]["count"]
    return (
        f"[{lottery_type}] {conc['status']} | 基线 E={base['E']:.3f} 阈值={base['threshold_95']:.3f} | "
        f"forward={forward_count} backward={backward_count} | {conc['message']}"
    )
