# -*- coding: utf-8 -*-
"""
大乐透预测结果表 (dlt_forecast) 的 ORM 模型。
"""
from sqlalchemy import Column, Integer, String, Date, Float, DateTime, UniqueConstraint, func

from app.core.database import Base


class DLTForecast(Base):
    __tablename__ = "dlt_forecast"
    # 同一开奖期同一模型只保留一条预测，数据库层保证 upsert 幂等
    __table_args__ = (
        UniqueConstraint('forecast_date', 'model_version', name='uk_dlt_forecast_date_model'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    forecast_date = Column(Date, nullable=False, comment="预测日期")
    group_id = Column(Integer, default=1, comment="分组ID")
    red_one = Column(Integer, nullable=False, comment="前区1")
    red_two = Column(Integer, nullable=False, comment="前区2")
    red_three = Column(Integer, nullable=False, comment="前区3")
    red_four = Column(Integer, nullable=False, comment="前区4")
    red_five = Column(Integer, nullable=False, comment="前区5")
    blue_one = Column(Integer, nullable=False, comment="后区1")
    blue_two = Column(Integer, nullable=False, comment="后区2")
    model_version = Column(String(128), default="Transformer", comment="模型版本")
    quality_score = Column(Float, nullable=True, comment="质量评分")
    is_removed = Column(Integer, default=0, comment="相似度剔除标记：0保留 1剔除")
    max_similarity = Column(Float, nullable=True, comment="与历史开奖最大相似度")
    matched_history_issue = Column(String(32), nullable=True, comment="最相似历史期号")
    create_time = Column(DateTime, server_default=func.now(), comment="创建时间")