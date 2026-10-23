# -*- coding: utf-8 -*-
"""
号码提取工具：统一从 ORM 行对象提取 (红/前区号码列表, 蓝/后区号码列表)。

字段命名差异（历史遗留）：
- history 表：ssq 用 red_*/blue_one；dlt 用 front_*/back_*
- forecast 表：两彩种均用 red_*，ssq 蓝球 blue_one；dlt 后区 blue_one/blue_two
所有需要"把一行记录转成号码列表"的地方都应走这里，避免字段映射散落多处。
"""


def extract_history_numbers(lottery_type: str, row):
    """从历史开奖记录提取 (红/前区列表, 蓝/后区列表)"""
    if lottery_type == 'ssq':
        reds = [row.red_one, row.red_two, row.red_three,
                row.red_four, row.red_five, row.red_six]
        blues = [row.blue_one]
    else:
        reds = [row.front_one, row.front_two, row.front_three,
                row.front_four, row.front_five]
        blues = [row.back_one, row.back_two]
    return reds, blues


def extract_forecast_numbers(lottery_type: str, row):
    """从预测记录提取 (红/前区列表, 蓝/后区列表)"""
    if lottery_type == 'ssq':
        reds = [row.red_one, row.red_two, row.red_three,
                row.red_four, row.red_five, row.red_six]
        blues = [row.blue_one]
    else:
        reds = [row.red_one, row.red_two, row.red_three,
                row.red_four, row.red_five]
        blues = [row.blue_one, row.blue_two]
    return reds, blues
