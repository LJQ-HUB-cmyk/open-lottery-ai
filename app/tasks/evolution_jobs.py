# -*- coding: utf-8 -*-
"""
自我进化闭环编排任务。

Celery Beat 每日定时触发（或经 API 手动触发），在数据更新后自动执行：
「抓取/检测新数据 → 回测打分 → 采样高命中率参数 → 批量训练 → 复测 → 晋升 → 集成预测入库」。

设计原则：复用现有 service 函数，不重复命中率/训练/回测/集成逻辑。
"""
import asyncio
import logging

from app.core.celery_app import celery_app
from app.core.config import settings
from app.services.fetch_service import run_fetch_script
from app.services.data_loader import get_max_issue_sync
from app.services.trainer import train_lottery_model
from app.services.backtest_service import (
    backtest_all_models, get_top_models, sample_recommended_params,
)
from app.services.diagnostic_service import run_diagnostic

logger = logging.getLogger(__name__)


def _backtest_progress(self, stage):
    """构造回测进度回调，把进度写入 Celery 任务状态。"""
    def _cb(done, total):
        self.update_state(
            state="RUNNING",
            meta={"stage": stage, "progress": f"{done}/{total}",
                  "message": f"{stage}：已回测 {done}/{total} 个模型"}
        )
    return _cb


@celery_app.task(bind=True, time_limit=86400, soft_time_limit=82800)
def run_self_evolution(self, lottery_type, n_models=None, force=False):
    """
    自我进化闭环编排任务。

    Args:
        lottery_type: 'ssq' 或 'dlt'
        n_models: 本轮训练模型数，None 时取配置 SELF_EVOLVE_N_MODELS
        force: True 时忽略「无新数据」闸门，强制跑一轮
    Returns:
        dict: 含 skipped / latest_issue / trained / champion / forecast 等
    """
    if lottery_type not in ('ssq', 'dlt'):
        raise Exception(f"未知彩种: {lottery_type}")

    n_models = n_models or settings.SELF_EVOLVE_N_MODELS
    summary = {"lottery_type": lottery_type, "n_models": n_models, "skipped": False}

    # ---------- 阶段 0：数据更新 + 新数据闸门 ----------
    self.update_state(
        state="FETCHING",
        meta={"stage": "fetch", "progress": "0%", "message": "正在检测/更新数据..."}
    )
    before_issue = get_max_issue_sync(lottery_type)

    fetch_result = run_fetch_script(lottery_type)
    if not fetch_result.get("success"):
        # FAILURE 状态由 Celery 统一回写，不写自定义 FAILURE meta
        raise Exception(f"数据抓取失败: {fetch_result.get('message')}")

    after_issue = get_max_issue_sync(lottery_type)
    if after_issue == before_issue and not force:
        summary["skipped"] = True
        summary["latest_issue"] = after_issue
        summary["reason"] = f"无新数据（最新期号仍为 {after_issue}），跳过本轮进化"
        logger.info("自我进化跳过：lottery_type=%s 无新数据", lottery_type)
        self.update_state(state="SUCCESS", meta={"stage": "done", "result": summary})
        return summary
    summary["latest_issue"] = after_issue

    # ---------- 阶段 1：存量模型基线回测（刷新 model_score，供 P2 采样） ----------
    self.update_state(
        state="RUNNING",
        meta={"stage": "baseline_backtest", "progress": "0%",
              "message": "正在回测存量模型..."}
    )
    backtest_all_models(lottery_type, progress_cb=_backtest_progress(self, "baseline_backtest"))

    # ---------- 阶段 2：双向批量训练（forward + backward 各训练 n_models 个） ----------
    trained = []
    for direction in ('forward', 'backward'):
        # 反向模型用小一点的 n_models（通常不需要等规模）
        dir_n = n_models if direction == 'forward' else max(2, n_models // 3)
        for i in range(dir_n):
            params = sample_recommended_params(lottery_type) or {}
            epochs = params.get("epochs", 50)
            batch_size = params.get("batch_size", 32)
            learning_rate = params.get("learning_rate", 1e-4)
            self.update_state(
                state="RUNNING",
                meta={"stage": "train",
                      "progress": f"{direction}-{i + 1}/{dir_n}",
                      "message": f"训练 {direction} 方向 第 {i + 1}/{dir_n} 个 "
                                 f"(epochs={epochs}, bs={batch_size}, lr={learning_rate:.6g})"}
            )
            result = train_lottery_model(
                lottery_type=lottery_type,
                epochs=epochs,
                batch_size=batch_size,
                lr=learning_rate,
                seed=None,
                direction=direction,
            )
            trained.append({
                "direction": direction,
                "run_id": result.get("run_id"),
                "best_hit_rate": result.get("best_hit_rate"),
                "epochs": epochs,
                "batch_size": batch_size,
                "learning_rate": learning_rate,
            })
    summary["trained"] = trained

    # ---------- 阶段 3：复测（新模型纳入 model_score） ----------
    self.update_state(
        state="RUNNING",
        meta={"stage": "rescore", "progress": "0%", "message": "正在复测全部模型..."}
    )
    backtest_all_models(lottery_type, progress_cb=_backtest_progress(self, "rescore"))

    # ---------- 阶段 4：诊断 + 双向一致性门控 ----------
    self.update_state(
        state="RUNNING",
        meta={"stage": "diagnostic", "progress": "0%",
              "message": "正在执行双向一致性诊断..."}
    )
    diag = run_diagnostic(lottery_type, n_periods=settings.BACKTEST_PERIODS)
    summary["diagnostic"] = diag
    diag_status = diag["conclusion"]["status"]

    if diag_status == "NO_SIGNAL":
        logger.warning("双向均无显著信号，本轮进化停止：%s", lottery_type)
        summary["evolution_decision"] = (
            "NO_SIGNAL 已确认 — 停止在噪音上过拟合，跳过晋升与集成预测"
        )
        self.update_state(state="SUCCESS",
                          meta={"stage": "done", "result": summary})
        return summary

    # INCONSISTENT 或 SIGNAL_DETECTED 都继续（但 INCONSISTENT 要告警）
    if diag_status == "INCONSISTENT":
        logger.warning("双向仅单方向显著（理论上不可能），继续但请注意：%s", lottery_type)
        summary["evolution_decision"] = "INCONSISTENT — 继续，但建议检查 train_end_issue 是否正确"
    else:
        summary["evolution_decision"] = "SIGNAL_DETECTED — 双向一致通过，晋升优质模型"

    # ---------- 阶段 5：晋升/排榜 ----------
    champions = get_top_models(lottery_type, settings.ENSEMBLE_TOP_K)
    summary["champion"] = champions

    # ---------- 阶段 6：集成预测入库 ----------
    self.update_state(
        state="RUNNING",
        meta={"stage": "predict", "progress": "0%", "message": "正在生成集成预测并入库..."}
    )
    try:
        from app.core.database import engine as _async_engine
        from app.services.ensemble_service import ensemble_predict

        async def _predict_and_dispose():
            try:
                return await ensemble_predict(lottery_type)
            finally:
                await _async_engine.dispose()

        forecast = asyncio.run(_predict_and_dispose())
        summary["forecast"] = forecast
    except Exception as e:
        logger.exception("集成预测失败：lottery_type=%s", lottery_type)
        summary["forecast_error"] = str(e)

    self.update_state(state="SUCCESS", meta={"stage": "done", "result": summary})
    logger.info("自我进化完成：%s → %s", lottery_type, diag_status)
    return summary
