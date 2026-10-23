# -*- coding: utf-8 -*-
"""
Transformer 模型定义，用于彩票序列预测。

增强版：
- 双头输出（红球头 + 蓝球头），分别处理红球（连续型 / 较大号码区间）与蓝球（小号码区间），
  相比单一 7 维输出能更好地分离两类目标的分布差异；
- 输出端改为带 LayerNorm + 残差连接的两层 MLP，增强表达能力；
- Encoder 前加 Input LayerNorm，缓解未归一化特征的数值波动；
- Dropout 可配置，支持训练时启用、预测时自动关闭。
"""
import math

import torch
import torch.nn as nn
from torch.utils.checkpoint import checkpoint


def _enable_fast_attention():
    """
    启用显存高效的注意力后端（PyTorch 2.0+ SDPA）。

    作用：FlashAttention / memory-efficient 后端把注意力显存从 O(seq_len²)
    降到 O(seq_len)，这是长序列（seq_len 上千）能在 8G 显存上训练的关键。
    """
    if not torch.cuda.is_available():
        return
    try:
        torch.backends.cuda.enable_flash_sdp(True)
        torch.backends.cuda.enable_mem_efficient_sdp(True)
    except Exception:
        pass
    try:
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
    except Exception:
        pass


_enable_fast_attention()


class PositionalEncoding(nn.Module):
    """位置编码，为序列添加位置信息"""
    def __init__(self, d_model, max_len=5000):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)  # (1, max_len, d_model)
        self.register_buffer('pe', pe)

    def forward(self, x):
        return x + self.pe[:, :x.size(1), :]


class MLPHead(nn.Module):
    """带残差 + LayerNorm 的两层 MLP 输出头"""
    def __init__(self, d_model, output_dim, dropout=0.1):
        super().__init__()
        self.norm = nn.LayerNorm(d_model)
        self.fc1 = nn.Linear(d_model, d_model)
        self.act = nn.GELU()
        self.drop = nn.Dropout(dropout)
        self.fc2 = nn.Linear(d_model, output_dim)

    def forward(self, x):
        # x: (batch, d_model)
        h = self.fc1(x)
        h = self.act(h)
        h = self.drop(h)
        # 残差连接（维度相同）
        h = self.norm(h + x)
        return self.fc2(h)


class LotteryTransformer(nn.Module):
    """
    彩票预测 Transformer 模型（双头版）。

    输入形状: (batch, seq_len, input_dim)
    输出形状: (batch, output_dim) 其中 output_dim = num_red + num_blue

    当 red_dim / blue_dim 同时给出时启用双头输出，分别预测红球与蓝球，
    在 forward 中拼接为 (batch, output_dim) 返回，保持向后兼容。
    """
    def __init__(self, input_dim, d_model=128, nhead=4, num_layers=3,
                 output_dim=7, red_dim=None, blue_dim=None, dropout=0.1):
        super().__init__()
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.red_dim = red_dim
        self.blue_dim = blue_dim
        self.dual_head = (red_dim is not None) and (blue_dim is not None)

        # 输入投影 + 输入归一化（缓解未归一特征波动）
        self.input_proj = nn.Linear(input_dim, d_model)
        self.input_norm = nn.LayerNorm(d_model)
        self.pos_enc = PositionalEncoding(d_model)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=d_model * 4,
            batch_first=True,
            dropout=dropout,
            activation='gelu'
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)

        # 输出头：双头 / 单头
        if self.dual_head:
            self.red_head = MLPHead(d_model, red_dim, dropout)
            self.blue_head = MLPHead(d_model, blue_dim, dropout)
        else:
            self.output_layer = MLPHead(d_model, output_dim, dropout)

    def forward(self, x):
        # x: (batch, seq_len, input_dim)
        x = self.input_proj(x)         # (batch, seq_len, d_model)
        x = self.input_norm(x)
        x = self.pos_enc(x)            # 加上位置编码
        x = self.encoder(x)           # (batch, seq_len, d_model)
        x = x[:, -1, :]                # 取最后一个时间步的输出

        if self.dual_head:
            red_out = self.red_head(x)     # (batch, red_dim)
            blue_out = self.blue_head(x)   # (batch, blue_dim)
            return torch.cat([red_out, blue_out], dim=-1)  # (batch, output_dim)
        return self.output_layer(x)        # (batch, output_dim)


class LotteryClassifier(nn.Module):
    """
    多标签分类彩票预测模型。

    输入: (batch, seq_len, input_dim) — 标准化特征 + multi-hot 历史
    输出: (batch, num_red + num_blue) — raw logits（配合 BCEWithLogitsLoss）

    核心改进：
    - 对每个可能号码输出独立概率（sigmoid），而非回归预测具体数值
    - 红/蓝分离双头，分别处理不同号码空间
    - 多层 MLP 残差头 + LayerNorm，增强表达力
    """
    def __init__(self, input_dim, d_model=128, nhead=4, num_layers=3,
                 num_red=33, num_blue=16, dropout=0.15, grad_checkpoint=False):
        super().__init__()
        self.input_dim = input_dim
        self.num_red = num_red
        self.num_blue = num_blue
        self.output_dim = num_red + num_blue
        # 梯度检查点：不保存中间激活，反向时重算。
        # 长序列下把激活显存压到约 1/√L，代价是约 30% 额外计算
        self.grad_checkpoint = grad_checkpoint

        # 输入投影 + 归一化
        self.input_proj = nn.Linear(input_dim, d_model)
        self.input_norm = nn.LayerNorm(d_model)
        self.pos_enc = PositionalEncoding(d_model)

        # Transformer Encoder
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=d_model * 4,
            batch_first=True,
            dropout=dropout,
            activation='gelu'
        )
        self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)

        # 多层残差分类头
        self.red_head = self._build_classifier_head(d_model, num_red, dropout)
        self.blue_head = self._build_classifier_head(d_model, num_blue, dropout)

        # 辅助：序列级聚合（mean pooling + last step）
        self.seq_proj = nn.Linear(d_model * 2, d_model)

    @staticmethod
    def _build_classifier_head(d_model, output_dim, dropout):
        """构建带残差连接的分类头"""
        return nn.Sequential(
            nn.LayerNorm(d_model),
            nn.Linear(d_model, d_model),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model, d_model // 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_model // 2, output_dim)
        )

    def forward(self, x):
        # x: (batch, seq_len, input_dim)
        x = self.input_proj(x)
        x = self.input_norm(x)
        x = self.pos_enc(x)
        if self.grad_checkpoint and self.training:
            # 逐层做梯度检查点：不缓存中间激活，反向传播时重算
            for layer in self.encoder.layers:
                x = checkpoint(layer, x, use_reentrant=False)
        else:
            x = self.encoder(x)           # (batch, seq_len, d_model)

        # 序列特征聚合：最后一步 + 全局均值
        last_step = x[:, -1, :]           # (batch, d_model)
        mean_step = x.mean(dim=1)         # (batch, d_model)
        seq_feat = torch.cat([last_step, mean_step], dim=-1)  # (batch, d_model*2)
        seq_feat = self.seq_proj(seq_feat)  # (batch, d_model)

        red_logits = self.red_head(seq_feat)    # (batch, num_red)
        blue_logits = self.blue_head(seq_feat)  # (batch, num_blue)
        return torch.cat([red_logits, blue_logits], dim=-1)  # (batch, output_dim)
