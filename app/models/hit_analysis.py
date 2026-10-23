# -*- coding: utf-8 -*-
"""
复试分析结果表 (hit_analysis) 的 ORM 模型。

复试 = 扩展号码池覆盖更多可能，提高中奖概率但成本按组合数 N 倍增加。
双色球 24 档: 7+1 ~ 12+4；大乐透 18 档: 6+2 ~ 11+4。

号码池来源：当期全部预测记录 × quality_score 加权频率统计 → Top-N 红/蓝。
"""
from sqlalchemy import Column, Integer, String, Date, Float, DateTime, UniqueConstraint, Index, func, text
from sqlalchemy.dialects.mysql import JSON, TINYINT

from app.core.database import Base


class HitAnalysis(Base):
    __tablename__ = "forecast_analysis"
    __table_args__ = (
        UniqueConstraint('lottery_type', 'forecast_date', 'pattern',
                         name='uk_forecast_analysis_lottery_date_pattern'),
        Index('idx_forecast_analysis_lottery_date', 'lottery_type', 'forecast_date'),
        # MySQL 表注释
        {'mysql_comment': '预测分析表 - 基于AI预测频率加权生成多档复试号码池、全部组合注及历史命中奖金'},
    )

    id = Column(Integer, primary_key=True, autoincrement=True,
                comment='主键自增ID')

    lottery_type = Column(String(8), nullable=False,
                          comment='彩种类型: ssq=双色球, dlt=大乐透')

    forecast_date = Column(Date, nullable=False,
                           comment='预测对应的开奖日期(YYYY-MM-DD)')

    pattern = Column(String(8), nullable=False,
                     comment='复试档位: 7+1/8+2/12+4等, 红球池大小+蓝球池大小')

    # ========== 号码池 ==========
    red_pool = Column(JSON, nullable=False,
                      comment='复试红球池(JSON数组,已按频率降序排列), 如[7,12,20,25,30,33,3,11]')

    blue_pool = Column(JSON, nullable=False,
                       comment='复试蓝球池(JSON数组,已按频率降序排列)')

    combo_detail = Column(JSON, nullable=False,
                          comment='全部组合注展开(JSON数组), 形如[{"red":[...], "blue":[...]}, ...], 注数=C(n红,k红)×C(n蓝,k蓝)')

    # ========== 金额统计 ==========
    bet_count = Column(Integer, nullable=False,
                       comment='组合注数 = C(红球池大小, pick_red) × C(蓝球池大小, pick_blue)')

    bet_amount = Column(Integer, nullable=False,
                        comment='投注总金额(元), 固定2元/注 × bet_count')

    freq_support = Column(Integer, nullable=False, default=0,
                          comment='当期参与号码池频率统计的AI预测记录条数')

    quality_avg = Column(Float, nullable=False, default=0.0,
                         comment='当期参与预测的平均质量分(quality_score均值), 范围0~1')

    # ========== 历史命中回填 ==========
    is_history_hit = Column(TINYINT, nullable=False, default=0,
                            comment='历史命中标记: 0=未评估/未中奖, 1=至少中过六等奖')

    hit_reds = Column(JSON, nullable=True,
                      comment='历史开奖后红命中数分布(JSON), 如{"0":5,"1":12,"2":18,"3":10}')

    hit_blues = Column(JSON, nullable=True,
                       comment='历史开奖后蓝命中数分布(JSON), 如{"0":40,"1":5}')

    prize_level = Column(String(16), nullable=True,
                         comment='历史最高命中奖级, 如: 一等奖/二等奖/.../九等奖/未中奖')

    prize_amount = Column(Integer, nullable=False, default=0,
                          comment='历史中奖金额合计(元), 仅固定奖级(三~九等奖)可算; 一/二等奖为浮动奖不计入')

    prize_detail = Column(JSON, nullable=True,
                          comment='各奖级中奖注数分布(JSON字典), 如{"六等奖":12,"五等奖":3}')

    float_prize_count = Column(Integer, nullable=False, default=0,
                               comment='一/二等奖(浮动奖)中奖注数, 具体金额需按当期官方公告核算')

    # ========== 优化元信息 ==========
    optimization_meta = Column(JSON, nullable=True,
                               comment='号码池优化元信息(JSON字典). '
                                       '旧版频率正向: {"strategy":"frequency"}; '
                                       'GA整合优化: {"strategy":"ga_integrated", "ga_meta":{...}}')

    # ========== 时间戳 ==========
    create_time = Column(DateTime, server_default=func.now(),
                         comment='记录创建时间')

    update_time = Column(DateTime, server_default=func.now(), onupdate=func.now(),
                         comment='记录最后更新时间(含重新生成复试时)')
