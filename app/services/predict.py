import torch
import numpy as np
from .transformer_model import LotteryTransformer
from .data_loader import load_lottery_data
from app.core.database import AsyncSessionLocal


async def predict_next(lottery_type: str, seq_len: int = 30):
    """预测下一期开奖号码"""
    async with AsyncSessionLocal() as db:
        data = await load_lottery_data(lottery_type, db)

    # 加载模型
    model = LotteryTransformer(input_dim=data.shape[1])
    model.load_state_dict(torch.load(f"./models_storage/{lottery_type}_final.pt"))
    model.eval()

    # 获取最近 seq_len 期数据
    recent = data.values[-seq_len:]
    input_tensor = torch.tensor(recent, dtype=torch.float32).unsqueeze(0)  # (1, seq_len, features)

    with torch.no_grad():
        prediction = model(input_tensor)

    # 后处理：将预测值转换为整数（红球1-33，蓝球1-16）
    pred = prediction.squeeze().numpy()
    reds = np.clip(np.round(pred[:6]), 1, 33).astype(int)
    blue = np.clip(np.round(pred[6]), 1, 16).astype(int)

    return {
        "red": sorted(reds.tolist()),
        "blue": int(blue)
    }