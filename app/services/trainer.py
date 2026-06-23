# -*- coding: utf-8 -*-
"""
训练器模块：使用历史数据训练 Transformer 模型，并保存模型和标准化参数。
支持双色球 (ssq) 和大乐透 (dlt) 两种彩种。
"""
import os
import joblib
import torch
import torch.nn as nn
import numpy as np
from torch.utils.data import DataLoader, TensorDataset
from sklearn.preprocessing import StandardScaler

from .data_loader import load_ssq_data_sync, load_dlt_data_sync   # 改为同步导入
from .transformer_model import LotteryTransformer
from app.core.config import settings


def train_lottery_model(lottery_type, epochs=50, batch_size=32, seq_len=30, lr=1e-4):
    """
    训练指定彩种的预测模型。
    """
    # ---------- 1. 加载数据（同步） ----------
    print(f"📊 开始加载 {lottery_type} 历史数据...")
    if lottery_type == 'ssq':
        df = load_ssq_data_sync()
    else:  # lottery_type == 'dlt'
        df = load_dlt_data_sync()

    if df is None or len(df) < seq_len + 1:
        raise ValueError(
            f"数据量不足，需要至少 {seq_len + 1} 条记录，"
            f"当前仅有 {len(df) if df is not None else 0} 条"
        )
    print(f"✅ 数据加载完成，共 {len(df)} 条记录")

    # ---------- 2-6 其余代码保持不变 ----------
    # ...（以下原样复制，省略重复）