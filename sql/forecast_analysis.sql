-- ==============================================
-- 表: forecast_analysis (模型数据明细表)
-- 说明: 基于AI预测频率加权生成多档复试号码池与全部组合注
-- 双色球: 24档 (7+1 ~ 12+4) | 大乐透: 18档 (6+2 ~ 11+4)
-- 字段来源: 当期全部预测记录 × quality_score 加权频率统计 → Top-N 红/蓝
-- ==============================================
DROP TABLE IF EXISTS `forecast_analysis`;
CREATE TABLE `forecast_analysis` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '主键自增ID',
  `lottery_type` varchar(8) NOT NULL COMMENT '彩种类型: ssq=双色球, dlt=大乐透',
  `forecast_date` date NOT NULL COMMENT '预测对应的开奖日期(YYYY-MM-DD)',
  `pattern` varchar(8) NOT NULL COMMENT '复试档位: 7+1/8+2/12+4等, 红球池大小+蓝球池大小',
  `red_pool` json NOT NULL COMMENT '复试红球池(JSON数组,已按频率降序排列), 如[7,12,20,25,30,33,3,11]',
  `blue_pool` json NOT NULL COMMENT '复试蓝球池(JSON数组,已按频率降序排列)',
  `combo_detail` json NOT NULL COMMENT '全部组合注展开(JSON数组), 形如[{"red":[...],"blue":[...]},...], 注数=C(n红,k红)×C(n蓝,k蓝)',
  `bet_count` int NOT NULL COMMENT '组合注数 = C(红球池大小, pick_red) × C(蓝球池大小, pick_blue)',
  `bet_amount` int NOT NULL COMMENT '投注总金额(元), 固定2元/注 × bet_count',
  `freq_support` int NOT NULL DEFAULT '0' COMMENT '当期参与号码池频率统计的AI预测记录条数',
  `quality_avg` float NOT NULL DEFAULT '0' COMMENT '当期参与预测的平均质量分(quality_score均值), 范围0~1',
  `is_history_hit` tinyint NOT NULL DEFAULT '0' COMMENT '历史命中标记: 0=未评估/未中奖, 1=至少中过六等奖',
  `hit_reds` json DEFAULT NULL COMMENT '历史开奖后红命中数分布(JSON字典), 键=红球命中个数(0~6), 值=注数',
  `hit_blues` json DEFAULT NULL COMMENT '历史开奖后蓝命中数分布(JSON字典), 键=蓝球命中个数(0~1), 值=注数',
  `prize_level` varchar(16) DEFAULT NULL COMMENT '历史最高命中奖级, 如: 一等奖/二等奖/.../六等奖/未中奖',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `update_time` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录最后更新时间(含重新生成复试时)',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_forecast_analysis_lottery_date_pattern` (`lottery_type`,`forecast_date`,`pattern`) USING BTREE,
  KEY `idx_forecast_analysis_lottery_date` (`lottery_type`,`forecast_date`) USING BTREE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='模型数据明细表 - 基于AI预测频率加权生成多档复试号码池与全部组合注';
