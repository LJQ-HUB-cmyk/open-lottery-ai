# -*- coding: utf-8 -*-
"""
模型真实命中率表：存储回测得到的每个模型的历史命中率，用于自我学习反馈。
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Float, DateTime, UniqueConstraint, Index

from app.core.database import Base


class ModelScore(Base):
    """模型回测命中率"""
    __tablename__ = "model_score"
    __table_args__ = (
        UniqueConstraint("lottery_type", "model_name", name="uq_model_score"),
        # 榜单查询固定按彩种过滤 + hit_total 降序排序，复合索引避免全表扫描+filesort
        Index("idx_model_score_type_total", "lottery_type", "hit_total"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    lottery_type = Column(String(10), nullable=False, comment="彩种: ssq/dlt")
    model_name = Column(String(128), nullable=False, comment="模型文件名")
    hit_red = Column(Float, default=0.0, comment="红球回测命中率")
    hit_blue = Column(Float, default=0.0, comment="蓝球回测命中率")
    hit_total = Column(Float, default=0.0, comment="综合命中率（红蓝均值）")
    evaluated_periods = Column(Integer, default=0, comment="回测期数")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")
