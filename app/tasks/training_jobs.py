# -*- coding: utf-8 -*-
"""
Celery 异步训练任务定义。
"""
import logging

from app.core.celery_app import celery_app
from app.services.fetch_service import run_fetch_script  # 新增
from app.services.trainer import train_lottery_model
from app.services.backtest_service import backtest_all_models

logger = logging.getLogger(__name__)


@celery_app.task(bind=True)
def start_training(self, lottery_type, epochs, batch_size, seq_len, learning_rate, seed=None):
    """
    异步训练任务，更新任务状态并返回训练结果。
    seed 为 None 时由 trainer 用时间戳自动生成，保证不同任务初始化权重不同。
    """
    self.update_state(
        state="RUNNING",
        meta={"lottery_type": lottery_type, "epochs": epochs, "progress": "0%"}
    )
    try:
        result = train_lottery_model(
            lottery_type=lottery_type,
            epochs=epochs,
            batch_size=batch_size,
            seq_len=seq_len,
            lr=learning_rate,
            seed=seed
        )
        self.update_state(
            state="SUCCESS",
            meta={"result": result, "progress": "100%"}
        )
        return result
    except Exception:
        # FAILURE 状态必须由 Celery 捕获异常后统一回写（标准 exc_type/exc_message 格式）；
        # 此处禁止 update_state(state="FAILURE") 写自定义 meta，否则结果后端解码缺 exc_type 会崩溃
        logger.exception("训练任务失败：lottery_type=%s, seq_len=%s", lottery_type, seq_len)
        raise


@celery_app.task(bind=True)
def run_full_pipeline(self, lottery_type, epochs, batch_size, seq_len, learning_rate, seed=None):
    """
    完整流水线任务：先执行数据抓取，再执行训练。
    seed 为 None 时由 trainer 用时间戳自动生成，保证不同任务初始化权重不同。
    状态阶段：fetch → train → done
    """
    # 1. 抓取阶段
    self.update_state(
        state="FETCHING",
        meta={"stage": "fetch", "progress": "0%", "message": "正在更新数据..."}
    )

    fetch_result = run_fetch_script(lottery_type)
    if not fetch_result['success']:
        # FAILURE 状态由抛出的异常统一回写，不写自定义 FAILURE meta
        raise Exception(f"数据抓取失败: {fetch_result['message']}")

    # 2. 训练阶段
    self.update_state(
        state="RUNNING",
        meta={"stage": "train", "progress": "0%", "message": "数据已更新，开始训练..."}
    )

    try:
        result = train_lottery_model(
            lottery_type=lottery_type,
            epochs=epochs,
            batch_size=batch_size,
            seq_len=seq_len,
            lr=learning_rate,
            seed=seed
        )
        self.update_state(
            state="SUCCESS",
            meta={"stage": "done", "result": result, "progress": "100%"}
        )
        return result
    except Exception:
        # FAILURE 状态由 Celery 统一回写，不写自定义 FAILURE meta
        logger.exception("流水线训练阶段失败：lottery_type=%s, seq_len=%s", lottery_type, seq_len)
        raise


@celery_app.task(bind=True)
def run_backtest(self, lottery_type, n_periods=None):
    """
    异步回测任务：回测彩种下所有模型的真实命中率，写入 model_score 表。
    n_periods 不传时由 backtest_service 取配置 BACKTEST_PERIODS。
    """
    self.update_state(
        state="RUNNING",
        meta={"stage": "backtest", "progress": "0%", "message": "开始回测..."}
    )
    try:
        result = backtest_all_models(
            lottery_type, n_periods=n_periods,
            progress_cb=lambda done, total: self.update_state(
                state="RUNNING",
                meta={"stage": "backtest", "progress": f"{done}/{total}",
                      "message": f"已回测 {done}/{total} 个模型"}
            )
        )
        self.update_state(
            state="SUCCESS",
            meta={"stage": "done", "result": result, "progress": "100%"}
        )
        return result
    except Exception:
        # FAILURE 状态由 Celery 统一回写，不写自定义 FAILURE meta
        logger.exception("回测任务失败：lottery_type=%s", lottery_type)
        raise