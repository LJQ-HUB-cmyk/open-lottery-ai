# -*- coding: utf-8 -*-
"""
轻量幂等迁移：Base.metadata.create_all 只会创建不存在的表，
不会为已存在的表补充新列或新索引。本模块在应用启动时检查并补齐
已知的 schema 变更（列、索引），避免人工手动执行 ALTER TABLE。

正式环境长期演进建议接入 Alembic；当前用此模块覆盖增量变更。
"""
from sqlalchemy import inspect, text

from .database import sync_engine

# (表名, 列名, ALTER TABLE 中 ADD COLUMN 的 DDL 片段)
_REQUIRED_COLUMNS = [
    ("ssq_forecast", "is_removed",
     "ADD COLUMN is_removed INT NOT NULL DEFAULT 0 COMMENT '相似度剔除标记：0保留 1剔除'"),
    ("ssq_forecast", "max_similarity",
     "ADD COLUMN max_similarity FLOAT NULL COMMENT '与历史开奖最大相似度'"),
    ("ssq_forecast", "matched_history_issue",
     "ADD COLUMN matched_history_issue VARCHAR(32) NULL COMMENT '最相似历史期号'"),
    ("dlt_forecast", "is_removed",
     "ADD COLUMN is_removed INT NOT NULL DEFAULT 0 COMMENT '相似度剔除标记：0保留 1剔除'"),
    ("dlt_forecast", "max_similarity",
     "ADD COLUMN max_similarity FLOAT NULL COMMENT '与历史开奖最大相似度'"),
    ("dlt_forecast", "matched_history_issue",
     "ADD COLUMN matched_history_issue VARCHAR(32) NULL COMMENT '最相似历史期号'"),
    # 复试命中奖金相关字段（预测分析表）
    ("forecast_analysis", "prize_amount",
     "ADD COLUMN prize_amount INT NOT NULL DEFAULT 0 "
     "COMMENT '历史中奖金额合计(元), 仅固定奖级(三~九等奖)可算; 一/二等奖为浮动奖不计入' "
     "AFTER prize_level"),
    ("forecast_analysis", "prize_detail",
     "ADD COLUMN prize_detail JSON NULL "
     "COMMENT '各奖级中奖注数分布(JSON字典), 如{\"六等奖\":12,\"五等奖\":3}' "
     "AFTER prize_amount"),
    ("forecast_analysis", "float_prize_count",
     "ADD COLUMN float_prize_count INT NOT NULL DEFAULT 0 "
     "COMMENT '一/二等奖(浮动奖)中奖注数, 具体金额需按当期官方公告核算' "
     "AFTER prize_detail"),
    # GA 优化元信息（复试最优方案整合）
    ("forecast_analysis", "optimization_meta",
     "ADD COLUMN optimization_meta JSON NULL "
     "COMMENT '号码池优化元信息(JSON字典). 旧版频率正向={\"strategy\":\"frequency\"}; GA整合={\"strategy\":\"ga_integrated\", \"ga_meta\":{...}}' "
     "AFTER float_prize_count"),
]

# (索引名, 表名, CREATE INDEX 完整 DDL)
_REQUIRED_INDEXES = [
    ("idx_model_score_type_total", "model_score",
     "CREATE INDEX idx_model_score_type_total ON model_score (lottery_type, hit_total)"),
]

# (唯一索引名, 表名, "列A, 列B")：建唯一索引前先按这两列去重（保留最小 id），
# 否则历史重复数据会导致 CREATE UNIQUE INDEX 失败。
_REQUIRED_UNIQUE_INDEXES = [
    ("uk_ssq_forecast_date_model", "ssq_forecast", "forecast_date, model_version"),
    ("uk_dlt_forecast_date_model", "dlt_forecast", "forecast_date, model_version"),
]


def run_migrations() -> dict:
    """
    检查并补齐缺失的列与索引。返回 {"added_columns": [...], "added_indexes": [...]}。
    全部为幂等操作：已存在则跳过。
    """
    added_columns, added_indexes = [], []
    with sync_engine.begin() as conn:
        insp = inspect(conn)
        existing_tables = set(insp.get_table_names())

        for table, column, ddl in _REQUIRED_COLUMNS:
            if table not in existing_tables:
                continue  # 表尚不存在，create_all 会按最新模型建表
            present = {c["name"] for c in insp.get_columns(table)}
            if column not in present:
                conn.execute(text(f"ALTER TABLE {table} {ddl}"))
                added_columns.append(f"{table}.{column}")

        # 列变更后刷新 inspector 视图
        insp = inspect(conn)
        for index_name, table, ddl in _REQUIRED_INDEXES:
            if table not in existing_tables:
                continue
            present = {i["name"] for i in insp.get_indexes(table)}
            if index_name not in present:
                conn.execute(text(ddl))
                added_indexes.append(index_name)

        # 唯一索引：先去重（同键保留最小 id，幂等无重复时影响 0 行），再建索引
        for index_name, table, columns in _REQUIRED_UNIQUE_INDEXES:
            if table not in existing_tables:
                continue
            present = {i["name"] for i in insp.get_indexes(table)}
            if index_name in present:
                continue
            col_a, col_b = [c.strip() for c in columns.split(",")]
            conn.execute(text(
                f"DELETE t FROM {table} t "
                f"JOIN (SELECT {col_a}, {col_b}, MIN(id) AS min_id FROM {table} "
                f"WHERE {col_b} IS NOT NULL GROUP BY {col_a}, {col_b} "
                f"HAVING COUNT(*) > 1) d "
                f"ON t.{col_a} = d.{col_a} AND t.{col_b} = d.{col_b} AND t.id > d.min_id"
            ))
            conn.execute(text(f"CREATE UNIQUE INDEX {index_name} ON {table} ({columns})"))
            added_indexes.append(index_name)

    return {"added_columns": added_columns, "added_indexes": added_indexes}
