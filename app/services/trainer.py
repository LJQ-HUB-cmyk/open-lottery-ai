# -*- coding: utf-8 -*-
"""
训练器模块：使用历史数据训练 Transformer 模型，并保存模型和标准化参数。
支持双色球 (ssq) 和大乐透 (dlt) 两种彩种。
"""
import os
import asyncio
import joblib
import torch
import torch.nn as nn
import numpy as np
from torch.utils.data import DataLoader, TensorDataset
from sklearn.preprocessing import StandardScaler

from .data_loader import load_ssq_data, load_dlt_data
from .transformer_model import LotteryTransformer
from app.core.config import settings


def train_lottery_model(lottery_type, epochs=50, batch_size=32, seq_len=30, lr=1e-4):
    """
    训练指定彩种的预测模型。

    Args:
        lottery_type (str): 彩种标识，'ssq' 或 'dlt'
        epochs (int): 训练轮数
        batch_size (int): 批次大小
        seq_len (int): 序列长度（使用多少期历史数据预测下一期）
        lr (float): 学习率

    Returns:
        dict: 包含模型路径、最终损失等信息，可用于日志记录。

    Raises:
        ValueError: 数据量不足以构成训练样本时抛出。
        Exception: 其他训练过程中的异常。
    """
    # ---------- 1. 加载数据（异步函数在同步环境中执行） ----------
    print(f"📊 开始加载 {lottery_type} 历史数据...")
    if lottery_type == 'ssq':
        # load_ssq_data 是异步函数，在同步函数中使用 asyncio.run() 执行
        df = asyncio.run(load_ssq_data())
    else:  # lottery_type == 'dlt'
        df = asyncio.run(load_dlt_data())

    if df is None or len(df) < seq_len + 1:
        raise ValueError(
            f"数据量不足，需要至少 {seq_len + 1} 条记录，"
            f"当前仅有 {len(df) if df is not None else 0} 条"
        )
    print(f"✅ 数据加载完成，共 {len(df)} 条记录")

    # ---------- 2. 标准化特征和目标 ----------
    # 将全部列（特征 + 目标）一起标准化，这样目标值也变为标准分布，
    # 有利于神经网络训练。但预测后需要进行逆标准化还原号码。
    scaler = StandardScaler()
    scaled = scaler.fit_transform(df.values)   # 所有列一起标准化

    # ---------- 3. 构造序列样本 ----------
    # 使用滑动窗口生成 (X, y) 对
    X, y = [], []
    for i in range(len(scaled) - seq_len):
        X.append(scaled[i:i + seq_len])          # 前 seq_len 期作为输入
        y.append(scaled[i + seq_len])            # 下一期的全部字段（包含特征和目标）
    X = np.array(X, dtype=np.float32)
    y = np.array(y, dtype=np.float32)

    # 目标只取最后 output_dim 个字段（即号码部分）
    output_dim = 7  # 双色球 6 红 + 1 蓝，大乐透 5 前区 + 2 后区，均为 7
    y_target = y[:, -output_dim:]   # 最后 output_dim 列是号码

    # 转换为 PyTorch Dataset
    dataset = TensorDataset(torch.tensor(X), torch.tensor(y_target))
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    # ---------- 4. 初始化模型 ----------
    input_dim = df.shape[1]   # 特征维度（所有列数）
    model = LotteryTransformer(
        input_dim=input_dim,
        d_model=128,          # Transformer 隐层维度
        nhead=4,              # 多头注意力头数
        num_layers=3,         # 编码器层数
        output_dim=output_dim
    )

    # 选择设备
    device = torch.device(settings.DEVICE if torch.cuda.is_available() else "cpu")
    model.to(device)
    print(f"💻 训练设备: {device}")

    optimizer = torch.optim.Adam(model.parameters(), lr=lr)
    criterion = nn.MSELoss()   # 回归任务使用均方误差

    # ---------- 5. 训练循环 ----------
    print(f"🚀 开始训练 {lottery_type} 模型，共 {epochs} 轮...")
    for epoch in range(epochs):
        total_loss = 0.0
        for batch_x, batch_y in loader:
            batch_x = batch_x.to(device)
            batch_y = batch_y.to(device)

            optimizer.zero_grad()
            pred = model(batch_x)          # 前向传播 (batch, output_dim)
            loss = criterion(pred, batch_y)
            loss.backward()
            optimizer.step()

            total_loss += loss.item()

        avg_loss = total_loss / len(loader)
        # 每 10 轮打印一次进度
        if (epoch + 1) % 10 == 0 or epoch == 0:
            print(f"  Epoch {epoch+1}/{epochs}, Loss: {avg_loss:.6f}")

    print("✅ 训练完成！")

    # ---------- 6. 保存模型和标准化器 ----------
    save_dir = settings.MODEL_SAVE_DIR
    os.makedirs(save_dir, exist_ok=True)

    model_path = os.path.join(save_dir, f"{lottery_type}_final.pt")
    torch.save(model.state_dict(), model_path)

    scaler_path = os.path.join(save_dir, f"{lottery_type}_scaler.joblib")
    joblib.dump(scaler, scaler_path)

    print(f"💾 模型已保存至: {model_path}")
    print(f"💾 标准化器已保存至: {scaler_path}")

    # 返回训练结果摘要
    return {
        "model_path": model_path,
        "scaler_path": scaler_path,
        "epochs": epochs,
        "final_loss": avg_loss,
        "lottery_type": lottery_type,
        "device": str(device)
    }