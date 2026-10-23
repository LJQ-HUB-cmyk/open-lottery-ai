# -*- coding: utf-8 -*-
"""
训练器模块：多标签分类方式训练 Transformer 模型。

核心改进（vs 旧版回归训练）：
- 多标签分类（BCEWithLogitsLoss）取代 MSE 回归
- 标准化仅作用于特征列，multi-hot 目标保持 0/1
- 号码频率特征 + 序列特征聚合（last + mean pooling）
- 训练中评估命中率（Top-K accuracy）
- Early Stopping + Cosine LR + 梯度裁剪 + Best Model
"""
import json
import logging
import os
import random
import time
from datetime import datetime

# 必须早于 import torch：让 CUDA 分配器使用可扩展段，减少长序列下的显存碎片
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import joblib
import numpy as np
import torch
import torch.nn as nn
from sklearn.preprocessing import StandardScaler

from app.core.config import settings
from .data_loader import (
    load_ssq_data_sync, load_dlt_data_sync, get_max_issue_sync,
    SSQ_FEATURE_COLS, SSQ_TARGET_COLS,
    DLT_FEATURE_COLS, DLT_TARGET_COLS,
    SSQ_RED_RANGE, SSQ_BLUE_RANGE,
    DLT_FRONT_RANGE, DLT_BACK_RANGE,
)
from .transformer_model import LotteryClassifier

logger = logging.getLogger(__name__)


def _free_vram_mb() -> float:
    """当前可用显存（MB）；非 CUDA 环境返回 0"""
    if not torch.cuda.is_available():
        return 0.0
    try:
        free, _total = torch.cuda.mem_get_info()
        return free / (1024 ** 2)
    except Exception:
        return 0.0


def _plan_batch_strategy(batch_size, seq_len, d_model, nhead, num_layers):
    """
    长序列训练策略：返回 (micro_batch, accum_steps, grad_checkpoint)。

    显存估算只按"最坏情况"做保守规划：
      - flash 生效：注意力显存 ≈ O(seq_len · d_model)
      - flash 未生效：注意力矩阵 ≈ O(seq_len² · nhead)，此时必须缩小 micro-batch 并开梯度检查点
    预算只取可用显存的 55%，留出临时张量与碎片余量。
    """
    free_mb = _free_vram_mb()
    if free_mb <= 0:
        return batch_size, 1, False

    head_dim = max(1, d_model // nhead)
    try:
        flash_ok = bool(torch.backends.cuda.flash_sdp_enabled()) and head_dim % 8 == 0
    except Exception:
        flash_ok = False

    if flash_ok:
        per_sample_mb = (seq_len * d_model * 2 * num_layers * 3) / (1024 ** 2)
    else:
        per_sample_mb = (
            seq_len * seq_len * nhead * 2 * num_layers * 3
            + seq_len * d_model * 2 * num_layers * 3
        ) / (1024 ** 2)

    budget_mb = free_mb * 0.55
    fit = max(1, int(budget_mb // max(per_sample_mb, 0.05)))
    micro = min(batch_size, fit)
    accum = max(1, (batch_size + micro - 1) // micro)
    # 长序列一律开梯度检查点：即使 flash 运行时回退到 math 后端也不会爆显存
    grad_ckpt = seq_len > 512 or ((not flash_ok) and (per_sample_mb * micro > budget_mb * 0.6))
    return micro, accum, grad_ckpt

# ==================== 超参默认值 ====================
DEFAULT_VAL_RATIO = 0.2
DEFAULT_PATIENCE = 15
DEFAULT_GRAD_CLIP = 1.0
DEFAULT_DROPOUT = 0.3          # 加大 dropout 缓解过拟合
DEFAULT_D_MODEL = 64           # 降低模型容量（彩票信号弱，大模型易过拟合）
DEFAULT_NHEAD = 4
DEFAULT_NUM_LAYERS = 2         # 减少层数
DEFAULT_WEIGHT_DECAY = 1e-3    # 加大权重衰减
PRED_SEQ_LEN = 30  # 预测时使用的序列长度（meta 实际存训练 seq_len）


def set_seed(seed: int = 42):
    """固定随机种子，保证可复现"""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


# TF32 加速（Ampere+ GPU 上 matmul 提速 2~3x，精度损失可忽略）
if torch.cuda.is_available():
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True


@torch.no_grad()
def _eval_one_pass(model, X_val, y_val, criterion, num_red, num_blue,
                   red_pick, blue_pick, batch_size=512):
    """
    单遍验证：同时计算 val_loss + 命中率（全部在 GPU 上向量化，无 Python 逐样本循环）。
    X_val / y_val 已在 GPU 上。
    返回 (val_loss, red_hit, blue_hit, total_hit)。
    """
    model.eval()
    total_val = 0.0
    n_batches = 0
    red_hit_sum = 0.0
    blue_hit_sum = 0.0
    n_samples = 0

    for start in range(0, len(X_val), batch_size):
        end = min(start + batch_size, len(X_val))
        batch_x = X_val[start:end]
        batch_y = y_val[start:end]

        with torch.autocast(device_type='cuda', dtype=torch.float16, enabled=batch_x.is_cuda):
            logits = model(batch_x).float()
        # reduction='none' 时返回 (B, C)，对类别求平均还原标量
        total_val += criterion(logits, batch_y).mean().item()
        n_batches += 1

        # sigmoid → 概率
        probs = torch.sigmoid(logits)
        red_probs = probs[:, :num_red]
        blue_probs = probs[:, num_red:]
        true_red = batch_y[:, :num_red]
        true_blue = batch_y[:, num_red:]

        # Top-K 预测的 one-hot（GPU 向量化）
        pred_red_idx = torch.topk(red_probs, k=min(red_pick, num_red), dim=1).indices
        pred_blue_idx = torch.topk(blue_probs, k=min(blue_pick, num_blue), dim=1).indices
        pred_red_oh = torch.zeros_like(red_probs).scatter_(1, pred_red_idx, 1.0)
        pred_blue_oh = torch.zeros_like(blue_probs).scatter_(1, pred_blue_idx, 1.0)

        # 命中数 / 真实号码数，逐样本求和
        bs = end - start
        red_hit_sum += ((pred_red_oh * true_red).sum(dim=1)
                        / true_red.sum(dim=1).clamp(min=1)).sum().item()
        blue_hit_sum += ((pred_blue_oh * true_blue).sum(dim=1)
                         / true_blue.sum(dim=1).clamp(min=1)).sum().item()
        n_samples += bs

    val_loss = total_val / max(n_batches, 1)
    r_hit = red_hit_sum / max(n_samples, 1)
    b_hit = blue_hit_sum / max(n_samples, 1)
    return val_loss, r_hit, b_hit, (r_hit + b_hit) / 2


def train_lottery_model(lottery_type, epochs=50, batch_size=32, seq_len=30, lr=1e-4,
                        seed: int = 42, patience: int = DEFAULT_PATIENCE,
                        val_ratio: float = DEFAULT_VAL_RATIO,
                        direction: str = 'forward'):
    """
    训练指定彩种的分类模型。

    Args:
        lottery_type: 'ssq' 或 'dlt'
        epochs: 训练轮数
        batch_size: 批次大小
        seq_len: 序列长度
        lr: 学习率
        seed: 随机种子
        patience: Early Stopping 耐心
        val_ratio: 验证集占比
        direction: 'forward'(默认) 学 y_t → y_{t+1}；'backward' 学 y_{t+1} → y_t（反向公式）

    Returns:
        dict: 模型路径、损失、命中率等信息
    """
    assert direction in ('forward', 'backward'), f"direction 必须是 'forward' 或 'backward'，收到 {direction}"
    # ---------- 0. 固定随机种子 ----------
    # seed 为 None 时用时间戳自动生成，避免批量训练时所有模型用相同种子导致输出趋同
    if seed is None:
        seed = int(time.time()) % 2147483647
        logger.info(f"🎲 未指定 seed，自动生成随机种子: {seed}")
    set_seed(seed)
    # Early Stopping：命中率连续 patience 轮无提升时提前结束（长训练时自动放宽）
    patience = max(patience, 20, epochs // 10)

    # ---------- 1. 加载数据 ----------
    logger.info(f"📊 开始加载 {lottery_type} 历史数据...")
    if lottery_type == 'ssq':
        df = load_ssq_data_sync()
        num_red, num_blue = SSQ_RED_RANGE, SSQ_BLUE_RANGE
        feature_cols = SSQ_FEATURE_COLS
        target_cols = SSQ_TARGET_COLS
        red_pick, blue_pick = 6, 1
    else:
        df = load_dlt_data_sync()
        num_red, num_blue = DLT_FRONT_RANGE, DLT_BACK_RANGE
        feature_cols = DLT_FEATURE_COLS
        target_cols = DLT_TARGET_COLS
        red_pick, blue_pick = 5, 2

    if df is None or len(df) < 2:
        raise ValueError(f"数据太少，无法训练，当前仅有 {len(df) if df is not None else 0} 条")

    # ---- 记录训练时数据截止期号（用于严格样本外回测过滤 t > train_end_issue） ----
    train_end_issue = get_max_issue_sync(lottery_type)
    logger.info(f"📌 训练数据截止期号 train_end_issue={train_end_issue}（direction={direction}）")

    # ---- 自适应调整 seq_len：只保留"能切出样本"的硬下限，不再强制预留 500 条 ----
    # 注意：数据并没有被"扣下"，训练窗口是按滑动方式覆盖全部期次的；
    # 这里限制的只是窗口数量 —— 样本数 = 总期数 - seq_len，seq_len 越大窗口越少。
    # 长序列本身由 Flash 注意力 / 梯度检查点 / micro-batch + 梯度累积支撑。
    MIN_SAMPLES = 50      # 硬下限：少于此值训练无意义（也留不出验证集）
    SAMPLE_WARN = 200     # 低于此值给出风险提示
    MAX_SEQ_LEN = 4096    # 位置编码容量上限（PositionalEncoding max_len=5000）
    sample_cap = len(df) - MIN_SAMPLES
    capped = min(seq_len, sample_cap, MAX_SEQ_LEN)
    if capped != seq_len:
        logger.info(
            f"⚠️ seq_len={seq_len} 超出可用范围，自动调整为 {capped}"
            f"（数据 {len(df)} 条，至少需能切出 {MIN_SAMPLES} 个窗口；上限 {MAX_SEQ_LEN}）")
        seq_len = capped
    if seq_len < 1:
        seq_len = 1
    total_windows = len(df) - seq_len
    if total_windows < SAMPLE_WARN:
        logger.warning(
            f"⚠️ seq_len={seq_len} 只能切出 {total_windows} 个训练窗口（< {SAMPLE_WARN}），"
            f"样本过少极易过拟合，建议降低序列长度让全部数据产生更多窗口")
    else:
        logger.info(f"🔢 seq_len={seq_len}，可切出训练窗口 {total_windows} 个")

    feature_dim = len(feature_cols)
    target_dim = len(target_cols)
    input_dim = feature_dim + target_dim  # 模型输入 = 特征 + multi-hot 历史
    output_dim = target_dim               # 模型输出 = multi-hot 预测

    logger.info(f"✅ 数据加载完成，共 {len(df)} 条，特征 {feature_dim} 维，目标 {target_dim} 维，seq_len={seq_len}")

    # ---------- 2. 提取原始特征与 multi-hot 目标（暂不标准化） ----------
    features = df[feature_cols].fillna(0).values.astype(np.float32)  # (N, feature_dim)
    targets = df[target_cols].values.astype(np.float32)              # (N, target_dim) 0/1

    # ---------- 3. 构造序列样本（特征窗口 + 历史 multi-hot 窗口） ----------
    X_feat, X_tgt, y = [], [], []
    # forward: f(y_t, y_{t-1}, ..., y_{t-L+1}) → y_{t+1}
    # backward: f(y_{t+1}, y_{t+2}, ..., y_{t+L}) → y_t（用"未来"的窗口回推当前）
    for i in range(len(features) - seq_len):
        if direction == 'forward':
            X_feat.append(features[i:i + seq_len])
            X_tgt.append(targets[i:i + seq_len])
            y.append(targets[i + seq_len])
        else:  # backward
            X_feat.append(features[i + 1:i + 1 + seq_len])
            X_tgt.append(targets[i + 1:i + 1 + seq_len])
            y.append(targets[i])
    X_feat = np.asarray(X_feat, dtype=np.float32)   # (S, seq_len, feature_dim)
    X_tgt = np.asarray(X_tgt, dtype=np.float32)     # (S, seq_len, target_dim)
    y = np.asarray(y, dtype=np.float32)             # (S, target_dim)

    # ---------- 4. 按时间切分训练 / 验证集 ----------
    total_samples = len(X_feat)
    val_count = max(1, int(total_samples * val_ratio))
    train_count = total_samples - val_count
    logger.info(f"📂 样本切分：训练 {train_count} 条 / 验证 {val_count} 条")

    # 标准化器只在训练段拟合：验证集/未来期不得参与均值方差计算，防止数据泄漏
    scaler = StandardScaler()
    scaler.fit(X_feat[:train_count].reshape(-1, feature_dim))
    X_feat_scaled = scaler.transform(
        X_feat.reshape(-1, feature_dim)).reshape(total_samples, seq_len, feature_dim)

    # 模型输入 = 标准化特征 + 原始 multi-hot 历史目标
    X = np.concatenate([X_feat_scaled, X_tgt], axis=2)  # (S, seq_len, input_dim)
    X_train, X_val = X[:train_count], X[train_count:]
    y_train, y_val = y[:train_count], y[train_count:]

    use_cuda = torch.cuda.is_available()
    device = torch.device(settings.DEVICE if use_cuda else "cpu")

    if use_cuda:
        # 数据集小（数百 MB），一次性移入 GPU，消除每批次 H2D 传输
        X_train_g = torch.tensor(X_train, dtype=torch.float32, device=device)
        y_train_g = torch.tensor(y_train, dtype=torch.float32, device=device)
        X_val_g = torch.tensor(X_val, dtype=torch.float32, device=device)
        y_val_g = torch.tensor(y_val, dtype=torch.float32, device=device)
    else:
        X_train_g = torch.tensor(X_train, dtype=torch.float32)
        y_train_g = torch.tensor(y_train, dtype=torch.float32)
        X_val_g = torch.tensor(X_val, dtype=torch.float32)
        y_val_g = torch.tensor(y_val, dtype=torch.float32)

    # ---------- 5. 初始化分类模型 ----------
    # 长序列显存规划：micro-batch 自适应 + 梯度累积保持等效 batch + 必要时开梯度检查点
    micro_bs, accum_steps, grad_ckpt = _plan_batch_strategy(
        batch_size, seq_len, DEFAULT_D_MODEL, DEFAULT_NHEAD, DEFAULT_NUM_LAYERS)

    model = LotteryClassifier(
        input_dim=input_dim,
        d_model=DEFAULT_D_MODEL,
        nhead=DEFAULT_NHEAD,
        num_layers=DEFAULT_NUM_LAYERS,
        num_red=num_red,
        num_blue=num_blue,
        dropout=DEFAULT_DROPOUT,
        grad_checkpoint=grad_ckpt,
    )

    model.to(device)
    logger.info(f"💻 训练设备: {device}，参数量: {sum(p.numel() for p in model.parameters() if p.requires_grad):,}")
    logger.info(
        f"🧩 长序列策略：micro_batch={micro_bs} × 累积 {accum_steps} 步 "
        f"(等效 batch {micro_bs * accum_steps})，seq_len={seq_len}，"
        f"梯度检查点={'开' if grad_ckpt else '关'}，可用显存 {_free_vram_mb():.0f}MB")

    # 正样本权重补偿：按各彩种实际每注号码个数计算正负比例（ssq 红6蓝1 / dlt 前5后2）
    red_pos_weight = torch.full((num_red,), (num_red - red_pick) / red_pick, device=device)
    blue_pos_weight = torch.full((num_blue,), (num_blue - blue_pick) / blue_pick, device=device)
    pos_weight = torch.cat([red_pos_weight, blue_pos_weight])

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=DEFAULT_WEIGHT_DECAY)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    # reduction='none'：返回 (B, C) 逐元素 loss，供训练循环按样本加权
    criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight, reduction='none')
    scaler_amp = torch.amp.GradScaler('cuda', enabled=use_cuda)  # fp16 混合精度

    # ---------- 5.5 错误样本加权（P1 自我学习闭环） ----------
    # 困难期次（Top-K 模型平均命中率 < 0.3）的训练样本权重 2.0，其他 1.0
    # 验证集不加权，仅训练集加权；困难期次映射：df 行号 t → 训练样本索引 t - seq_len
    sample_weights = None
    try:
        from .backtest_service import get_hard_periods
        hard_periods = get_hard_periods(lottery_type)
        if hard_periods:
            weights_arr = np.ones(train_count, dtype=np.float32)
            n_hard = 0
            for t in hard_periods:
                j = t - seq_len
                if 0 <= j < train_count:
                    weights_arr[j] = 2.0
                    n_hard += 1
            if n_hard > 0:
                sample_weights = torch.tensor(weights_arr, device=device)
                logger.info(f"⚖️ 错误样本加权：困难期次 {len(hard_periods)} 个，"
                            f"训练集命中 {n_hard} 个（权重 2.0），其余 1.0")
            else:
                logger.info(f"⚖️ 困难期次 {len(hard_periods)} 个均不在训练集范围，本次不加权")
    except Exception:
        logger.warning("获取困难期次失败，本次不加权", exc_info=True)

    # ---------- 5.6 弱点号码加权（P3 弱点强化） ----------
    # 经常被 Top-K 模型漏掉的号码，训练时对这些列 loss 乘 2.0
    # class_weights: (target_dim,)，弱点号码=2.0，其他=1.0
    class_weights = None
    try:
        from .backtest_service import get_weak_numbers
        weak = get_weak_numbers(lottery_type)
        red_weak, blue_weak = weak.get("red", set()), weak.get("blue", set())
        if red_weak or blue_weak:
            cw = np.ones(target_dim, dtype=np.float32)
            for n in red_weak:
                if 0 <= n < num_red:
                    cw[n] = 2.0
            for n in blue_weak:
                if 0 <= n < num_blue:
                    cw[num_red + n] = 2.0
            class_weights = torch.tensor(cw, device=device)
            logger.info(f"🎯 弱点号码加权：红球 {len(red_weak)} 个 / 蓝球 {len(blue_weak)} 个"
                        f"（权重 2.0），其余 1.0")
    except Exception:
        logger.warning("获取弱点号码失败，本次不加权", exc_info=True)

    # ---------- 6. 训练循环 ----------
    # Best Model 依据：验证集综合命中率（而非 BCE loss），因为彩票场景 loss 低 ≠ 命中高
    best_val_loss = float('inf')
    best_epoch = 0
    no_improve = 0
    best_state = None
    best_hit_rate = -1.0
    best_val_loss_at_best = float('inf')
    history = {'train_loss': [], 'val_loss': [], 'lr': [], 'hit_rate': []}

    logger.info(f"🚀 开始训练 {lottery_type} 分类模型，共 {epochs} 轮 (patience={patience})...")
    n_train = len(X_train_g)
    for epoch in range(epochs):
        # ---- 训练（GPU 张量直接切片，无 DataLoader 开销；AMP fp16 加速） ----
        model.train()
        total_train = 0.0
        n_micro = 0
        perm = torch.randperm(n_train, device=device)
        optimizer.zero_grad(set_to_none=True)
        for start in range(0, n_train, micro_bs):
            idx = perm[start:start + micro_bs]
            batch_x, batch_y = X_train_g[idx], y_train_g[idx]
            with torch.autocast(device_type='cuda', dtype=torch.float16, enabled=use_cuda):
                logits = model(batch_x)
                if sample_weights is not None or class_weights is not None:
                    # reduction='none' 返回 (B, C)，先按号码列加权再按样本加权
                    per_elem = criterion(logits, batch_y)
                    if class_weights is not None:
                        per_elem = per_elem * class_weights  # (B, C) * (C,)
                    loss_per_sample = per_elem.mean(dim=1)  # (B,)
                    if sample_weights is not None:
                        w = sample_weights[idx]
                        loss = (loss_per_sample * w).sum() / w.sum()
                    else:
                        loss = loss_per_sample.mean()
                else:
                    loss = criterion(logits, batch_y).mean()
            total_train += float(loss.detach())
            # 梯度累积：把 micro-batch 的梯度累加成等效大 batch
            scaler_amp.scale(loss / accum_steps).backward()
            n_micro += 1
            if n_micro % accum_steps == 0:
                scaler_amp.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), DEFAULT_GRAD_CLIP)
                scaler_amp.step(optimizer)
                scaler_amp.update()
                optimizer.zero_grad(set_to_none=True)
        # 尾部不足一个累积组的梯度补做一次更新
        if n_micro % accum_steps != 0:
            scaler_amp.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), DEFAULT_GRAD_CLIP)
            scaler_amp.step(optimizer)
            scaler_amp.update()
            optimizer.zero_grad(set_to_none=True)
        train_loss = total_train / max(n_micro, 1)

        # ---- 验证：单遍同时算 val_loss + 命中率（GPU 向量化） ----
        val_loss, r_hit, b_hit, t_hit = _eval_one_pass(
            model, X_val_g, y_val_g, criterion, num_red, num_blue,
            red_pick, blue_pick
        )
        history['hit_rate'].append({'epoch': epoch + 1, 'red': r_hit, 'blue': b_hit, 'total': t_hit})

        scheduler.step()
        cur_lr = optimizer.param_groups[0]['lr']
        history['train_loss'].append(float(train_loss))
        history['val_loss'].append(float(val_loss))
        history['lr'].append(float(cur_lr))

        # Best Model 依据综合命中率
        improved = t_hit > best_hit_rate
        if improved:
            best_hit_rate = t_hit
            best_val_loss_at_best = val_loss
            best_epoch = epoch + 1
            no_improve = 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            no_improve += 1
            if val_loss < best_val_loss:
                best_val_loss = val_loss

        tag = "🌟 best" if improved else ""
        logger.info(f"  Epoch {epoch+1:3d}/{epochs} | train {train_loss:.6f} | val {val_loss:.6f} | "
              f"hit R:{r_hit:.1%} B:{b_hit:.1%} T:{t_hit:.1%} | lr {cur_lr:.2e} {tag}")

        if no_improve >= patience:
            logger.info(f"⏹️  Early Stopping：连续 {patience} 轮命中率无提升，提前结束（最佳轮次 {best_epoch}）")
            break

    # 恢复最佳权重（命中率最高的 epoch）
    if best_state is not None:
        model.load_state_dict(best_state)
        logger.info(f"✅ 已恢复最佳模型权重（epoch {best_epoch}，命中率={best_hit_rate:.1%}，val_loss={best_val_loss_at_best:.6f}）")

    # 最终命中率评估（单遍 GPU 向量化）
    _, r_hit, b_hit, t_hit = _eval_one_pass(
        model, X_val_g, y_val_g, criterion, num_red, num_blue,
        red_pick, blue_pick
    )
    logger.info(f"🎯 最终命中率：红球 {r_hit:.1%} / 蓝球 {b_hit:.1%} / 综合 {t_hit:.1%}")

    # 释放 GPU 显存中的训练数据
    del X_train_g, y_train_g, X_val_g, y_val_g
    if use_cuda:
        torch.cuda.empty_cache()

    # ---------- 7. 保存模型、标准化器、元信息 ----------
    base_dir = settings.MODEL_SAVE_DIR
    save_dir = os.path.join(base_dir, lottery_type)
    os.makedirs(save_dir, exist_ok=True)

    param_str = f"dir{direction}_epochs{epochs}_bs{batch_size}_seq{seq_len}_lr{str(lr).replace('.', '_')}"
    timestamp = int(time.time())
    run_id = f"{lottery_type}_{param_str}_{timestamp}"

    model_path = os.path.join(save_dir, f"{run_id}.pt")
    scaler_path = os.path.join(save_dir, f"{run_id}_scaler.joblib")
    history_path = os.path.join(save_dir, f"{run_id}_history.json")
    meta_path = os.path.join(save_dir, f"{run_id}_meta.json")

    torch.save(model.state_dict(), model_path)
    joblib.dump(scaler, scaler_path)

    meta = {
        "model_type": "classifier",
        "run_id": run_id,
        "lottery_type": lottery_type,
        "direction": direction,              # forward=正推  上一期→下一期; backward=反推  下一期→上一期
        "train_end_issue": train_end_issue,  # 训练时数据最大期号（严格样本外回测时过滤 t <= train_end_issue）
        "epochs": epochs,
        "batch_size": batch_size,
        "seq_len": seq_len,
        "learning_rate": lr,
        "seed": seed,
        "patience": patience,
        "val_ratio": val_ratio,
        "feature_dim": feature_dim,
        "target_dim": target_dim,
        "input_dim": input_dim,
        "output_dim": output_dim,
        "num_red": num_red,
        "num_blue": num_blue,
        "best_epoch": best_epoch,
        "best_val_loss": float(best_val_loss_at_best),
        "best_hit_rate": float(best_hit_rate),
        "final_hit_rate": float(t_hit),
        "final_train_loss": float(history['train_loss'][-1]) if history['train_loss'] else None,
        "final_val_loss": float(history['val_loss'][-1]) if history['val_loss'] else None,
        "device": str(device),
        "timestamp": timestamp,  # 训练 Unix 时间戳（与文件名末尾一致，供本期过滤）
        "trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # 可读训练时间
        "d_model": DEFAULT_D_MODEL,
        "nhead": DEFAULT_NHEAD,
        "num_layers": DEFAULT_NUM_LAYERS,
        "dropout": DEFAULT_DROPOUT,
        "pred_seq_len": seq_len,  # 预测时使用与训练相同的序列长度
    }
    with open(history_path, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # 覆盖 final 版本（仅正向模型覆盖；反向模型独立存，不覆盖正向 final）
    final_model_path = None
    if direction == 'forward':
        final_model_path = os.path.join(save_dir, f"{lottery_type}_final.pt")
        final_scaler_path = os.path.join(save_dir, f"{lottery_type}_scaler.joblib")
        final_meta_path = os.path.join(save_dir, f"{lottery_type}_final_meta.json")
        torch.save(model.state_dict(), final_model_path)
        joblib.dump(scaler, final_scaler_path)
        with open(final_meta_path, 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    logger.info(f"💾 模型: {model_path}  (direction={direction})")
    logger.info(f"💾 标准化器: {scaler_path}")
    logger.info(f"💾 训练曲线: {history_path}")
    logger.info(f"💾 元信息: {meta_path}")
    if direction == 'forward':
        logger.info(f"💾 同时覆盖 final 版本: {final_model_path}")

    result = {
        "model_path": model_path,
        "scaler_path": scaler_path,
        "history_path": history_path,
        "meta_path": meta_path,
        "final_model_path": final_model_path,
        "epochs": epochs,
        "best_epoch": best_epoch,
        "best_val_loss": float(best_val_loss_at_best),
        "best_hit_rate": float(best_hit_rate),
        "final_hit_rate": float(t_hit),
        "final_train_loss": float(history['train_loss'][-1]) if history['train_loss'] else None,
        "final_val_loss": float(history['val_loss'][-1]) if history['val_loss'] else None,
        "lottery_type": lottery_type,
        "device": str(device),
        "run_id": run_id,
        "input_dim": input_dim,
        "output_dim": output_dim,
        "model_type": "classifier",
    }
    logger.info(f"📊 训练结果: {result}")

    # 保留所有训练的模型，不再清理（用户要求保留全部训练成果）
    # cleanup_old_models 已增强 low_score_threshold 参数，需要时取消下方注释即可启用
    # try:
    #     cleaned = cleanup_old_models(lottery_type, low_score_threshold=0.05)
    #     if cleaned["deleted"]:
    #         logger.info(f"🧹 清理模型 {len(cleaned['deleted'])} 个，删除三件套文件 "
    #                     f"{3 * len(cleaned['deleted'])} 个")
    # except Exception:
    #     logger.warning("模型磁盘清理失败（不影响训练结果）", exc_info=True)

    return result


def _model_file_timestamp(filename: str) -> int:
    """从模型文件名末尾解析 Unix 时间戳，失败返回 0"""
    try:
        return int(os.path.basename(filename)[:-3].rsplit("_", 1)[-1])
    except (ValueError, IndexError):
        return 0


def cleanup_old_models(lottery_type: str, keep_latest: int = None,
                       keep_top_scored: int = None,
                       low_score_threshold: float = None) -> dict:
    """
    清理磁盘上过旧的模型三件套（.pt / _scaler.joblib / _meta.json）。
    保留：本期（最近一期开奖后训练）的全部模型 + 最近 keep_latest 个模型 +
    回测榜单前 keep_top_scored 个 + 所有 *_final 版本；其余删除。
    P4 自适应淘汰：low_score_threshold > 0 时，已回测且 hit_total < 阈值的模型
    优先删除（即使较新，但 Top keep_top_scored 不受影响）。
    评分记录在 model_score 表中不受影响。
    """
    import glob
    from datetime import datetime, time as dtime
    from sqlalchemy import select, func
    from app.core.database import SyncSessionLocal
    from app.models.model_score import ModelScore
    from app.models.ssq_history import SSQHistory
    from app.models.dlt_history import DLTHistory

    keep_latest = keep_latest or settings.MODEL_KEEP_LATEST
    keep_top_scored = keep_top_scored or settings.MODEL_KEEP_TOP_SCORED
    model_dir = os.path.join(settings.MODEL_SAVE_DIR, lottery_type)
    if not os.path.isdir(model_dir):
        return {"deleted": []}

    # 普通模型（排除 _final），按训练时间戳新→旧排序
    pt_files = [f for f in glob.glob(os.path.join(model_dir, "*.pt"))
                if not os.path.basename(f).endswith("_final.pt")]
    pt_files.sort(key=_model_file_timestamp, reverse=True)

    # 本期模型全部保留：训练时间戳 >= 最近一期开奖日 00:00
    # （开奖结果导入后训练的模型都算本期，避免裁剪本期训练成果）
    period_start_ts = 0
    try:
        hist_model = SSQHistory if lottery_type == 'ssq' else DLTHistory
        with SyncSessionLocal() as session:
            last_draw = session.execute(
                select(func.max(hist_model.draw_date))
            ).scalar()
            if last_draw is not None:
                period_start_ts = int(datetime.combine(last_draw, dtime.min).timestamp())
    except Exception:
        logger.warning("查询最近开奖日失败，本次不按本期保留", exc_info=True)

    keep_names = set()
    if period_start_ts > 0:
        for f in pt_files:
            ts = _model_file_timestamp(f)
            if ts is not None and ts >= period_start_ts:
                keep_names.add(os.path.basename(f))
        logger.info("本期（开奖日后 ts>=%d）保留 %d 个模型", period_start_ts, len(keep_names))

    # 最近 keep_latest 个模型保留（兜底，覆盖本期外的近期模型）
    keep_names.update(os.path.basename(f) for f in pt_files[:keep_latest])

    # 回测榜单 Top M 的模型文件额外保留（即使较旧，集成/复现仍可能引用）
    top_names = set()
    try:
        with SyncSessionLocal() as session:
            rows = session.execute(
                select(ModelScore.model_name).where(
                    ModelScore.lottery_type == lottery_type
                ).order_by(ModelScore.hit_total.desc()).limit(keep_top_scored)
            ).all()
            top_names = {name for (name,) in rows if name}
            keep_names.update(top_names)
    except Exception:
        logger.warning("读取回测榜单失败，本次仅按最近 %d 个模型保留", keep_latest, exc_info=True)

    # P4 自适应淘汰：已回测且 hit_total < 阈值的模型优先删除（Top keep_top_scored 不受影响）
    if low_score_threshold and low_score_threshold > 0:
        try:
            with SyncSessionLocal() as session:
                low_score_names = {name for (name,) in session.execute(
                    select(ModelScore.model_name).where(
                        ModelScore.lottery_type == lottery_type,
                        ModelScore.hit_total < low_score_threshold
                    )
                ).all()}
            remove_set = low_score_names - top_names
            keep_names -= remove_set
            logger.info("📉 低分淘汰（hit_total<%.2f）移除 %d 个模型",
                        low_score_threshold, len(remove_set))
        except Exception:
            logger.warning("低分淘汰查询失败", exc_info=True)

    deleted = []
    for f in pt_files:
        name = os.path.basename(f)
        if name in keep_names:
            continue
        run_id = name[:-3]  # 去掉 .pt
        for suffix, prefix in ((".pt", ""), ("_scaler.joblib", ""), ("_meta.json", "")):
            target = os.path.join(model_dir, run_id + suffix)
            try:
                if os.path.exists(target):
                    os.remove(target)
            except OSError:
                logger.warning("删除模型文件失败: %s", target)
        deleted.append(name)

    return {"deleted": deleted}
