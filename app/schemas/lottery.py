# -*- coding: utf-8 -*-
"""
API 请求与响应的 Pydantic 模型定义。
"""
from datetime import date
from typing import Optional, List

from pydantic import BaseModel


# ---------- 基础响应 ----------
class SSQHistoryResponse(BaseModel):
    """双色球历史数据响应"""
    id: int
    issue_num: str
    draw_date: date
    red_one: int
    red_two: int
    red_three: int
    red_four: int
    red_five: int
    red_six: int
    blue_one: int
    red_summation: Optional[int] = None
    red_span: Optional[int] = None

    class Config:
        from_attributes = True

class DLTHistoryResponse(BaseModel):
    """大乐透历史数据响应"""
    id: int
    issue_num: str
    draw_date: date
    front_one: int
    front_two: int
    front_three: int
    front_four: int
    front_five: int
    back_one: int
    back_two: int
    front_summation: Optional[int] = None
    front_span: Optional[int] = None

    class Config:
        from_attributes = True

# ---------- 训练请求 ----------
class TrainRequest(BaseModel):
    """训练任务请求"""
    lottery_type: str = "ssq"          # 'ssq' 或 'dlt'
    epochs: int = 50
    batch_size: int = 32
    seq_len: int = 30
    learning_rate: float = 1e-4
    with_fetch: bool = True
    seed: Optional[int] = None         # 随机种子，None 时由 trainer 用时间戳自动生成
    auto_params: bool = False          # True 时从高命中率模型超参区间采样 epochs/batch_size/learning_rate

# ---------- 自我进化请求 ----------
class EvolveRequest(BaseModel):
    """自我进化闭环手动触发请求"""
    lottery_type: str = "ssq"          # 'ssq' 或 'dlt'
    n_models: Optional[int] = None     # 本轮训练模型数，None 时取配置 SELF_EVOLVE_N_MODELS
    force: bool = False                # True 时忽略「无新数据」闸门，强制跑一轮

class TrainResponse(BaseModel):
    """训练任务响应"""
    task_id: str
    status: str
    message: str

# ---------- 预测请求/响应 ----------
class PredictRequest(BaseModel):
    """预测请求"""
    lottery_type: str = "ssq"
    model_version: Optional[str] = "latest"
    model_name: Optional[str] = None   # 新增：指定具体模型文件名（如 ssq_epochs50_bs32_seq30_lr0_0001_1234567890.pt）

class PredictResponse(BaseModel):
    """预测响应"""
    lottery_type: str
    forecast_date: date
    red: List[int]
    blue: List[int]
    quality_score: Optional[float] = None
    model_version: str = "Transformer"


class BatchPredictRequest(BaseModel):
    """批量预测请求：一次提交多个模型文件名，后端并行推理"""
    models: List[str] = []
    max_workers: Optional[int] = 16