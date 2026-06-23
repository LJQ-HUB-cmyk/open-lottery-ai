# -*- coding: utf-8 -*-
"""
Celery 异步训练任务定义。
"""
from app.core.celery_app import celery_app
from app.services.trainer import train_lottery_model

@celery_app.task(bind=True)
def start_training(self, lottery_type, epochs, batch_size, seq_len, learning_rate):
    """
    异步训练任务，更新任务状态并返回训练结果。
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
            lr=learning_rate
        )
        self.update_state(
            state="SUCCESS",
            meta={"result": result, "progress": "100%"}
        )
        return result
    except Exception as e:
        self.update_state(
            state="FAILURE",
            meta={"error": str(e)}
        )
        raise e