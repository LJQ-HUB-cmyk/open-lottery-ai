/*
 Navicat Premium Dump SQL

 Source Server         : mysql
 Source Server Type    : MySQL
 Source Server Version : 80408 (8.4.8)
 Source Host           : 192.168.2.10:3306
 Source Schema         : open-lottery

 Target Server Type    : MySQL
 Target Server Version : 80408 (8.4.8)
 File Encoding         : 65001

 Date: 23/06/2026 20:48:12
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for dlt_all
-- ----------------------------
DROP TABLE IF EXISTS `dlt_all`;
CREATE TABLE `dlt_all`  (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `front_one` int NOT NULL,
  `front_two` int NOT NULL,
  `front_three` int NOT NULL,
  `front_four` int NOT NULL,
  `front_five` int NOT NULL,
  `back_one` int NOT NULL,
  `back_two` int NOT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_front`(`front_one` ASC, `front_two` ASC, `front_three` ASC, `front_four` ASC, `front_five` ASC) USING BTREE,
  INDEX `idx_back`(`back_one` ASC, `back_two` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 21765713 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '大乐透全部' ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- Table structure for dlt_forecast
-- ----------------------------
DROP TABLE IF EXISTS `dlt_forecast`;
CREATE TABLE `dlt_forecast`  (
  `id` int NOT NULL AUTO_INCREMENT,
  `forecast_date` date NOT NULL,
  `group_id` int NOT NULL DEFAULT 1,
  `red_one` int NOT NULL,
  `red_two` int NOT NULL,
  `red_three` int NOT NULL,
  `red_four` int NOT NULL,
  `red_five` int NOT NULL,
  `blue_one` int NOT NULL,
  `blue_two` int NOT NULL,
  `model_version` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT 'LSTM_Attention',
  `create_time` datetime NULL DEFAULT CURRENT_TIMESTAMP,
  `quality_score` float NULL DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_forecast_date`(`forecast_date` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 8 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '大乐透预测' ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- Table structure for dlt_history
-- ----------------------------
DROP TABLE IF EXISTS `dlt_history`;
CREATE TABLE `dlt_history`  (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `issue_num` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '期号（如2025001）',
  `draw_date` date NOT NULL COMMENT '开奖日期',
  `weekday` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '星期几',
  `year` int NULL DEFAULT NULL COMMENT '年份',
  `month` int NULL DEFAULT NULL COMMENT '月份',
  `quarter` int NULL DEFAULT NULL COMMENT '季度',
  `front_one` int NOT NULL COMMENT '前区1',
  `front_two` int NOT NULL COMMENT '前区2',
  `front_three` int NOT NULL COMMENT '前区3',
  `front_four` int NOT NULL COMMENT '前区4',
  `front_five` int NOT NULL COMMENT '前区5',
  `back_one` int NOT NULL COMMENT '后区1',
  `back_two` int NOT NULL COMMENT '后区2',
  `front_max` int NULL DEFAULT NULL COMMENT '前区最大值',
  `front_min` int NULL DEFAULT NULL COMMENT '前区最小值',
  `front_span` int NULL DEFAULT NULL COMMENT '前区跨度（max-min）',
  `front_summation` int NULL DEFAULT NULL COMMENT '前区和值',
  `front_summation_tail` int NULL DEFAULT NULL COMMENT '和值尾数',
  `front_odd_count` int NULL DEFAULT NULL COMMENT '前区奇数个数',
  `front_even_count` int NULL DEFAULT NULL COMMENT '前区偶数个数',
  `front_small_count` int NULL DEFAULT NULL COMMENT '前区小数个数（1-17为小，18-35为大）',
  `front_big_count` int NULL DEFAULT NULL COMMENT '前区大数个数',
  `front_prime_count` int NULL DEFAULT NULL COMMENT '前区质数个数',
  `front_composite_count` int NULL DEFAULT NULL COMMENT '前区合数个数',
  `front_mod0_count` int NULL DEFAULT NULL COMMENT '除3余0个数',
  `front_mod1_count` int NULL DEFAULT NULL COMMENT '除3余1个数',
  `front_mod2_count` int NULL DEFAULT NULL COMMENT '除3余2个数',
  `front_zone1_count` int NULL DEFAULT NULL COMMENT '一区个数（1-12）',
  `front_zone2_count` int NULL DEFAULT NULL COMMENT '二区个数（13-24）',
  `front_zone3_count` int NULL DEFAULT NULL COMMENT '三区个数（25-35）',
  `front_consecutive_groups` int NULL DEFAULT NULL COMMENT '连号组数',
  `front_consecutive_max_len` int NULL DEFAULT NULL COMMENT '最大连号长度',
  `front_repeat_count` int NULL DEFAULT NULL COMMENT '与上期前区重复个数',
  `front_ac_value` int NULL DEFAULT NULL COMMENT 'AC值',
  `front_first_last_sum` int NULL DEFAULT NULL COMMENT '首尾和',
  `front_middle_avg` decimal(5, 2) NULL DEFAULT NULL COMMENT '前区均值',
  `front_std_dev` decimal(8, 4) NULL DEFAULT NULL COMMENT '前区标准差',
  `back_odd_count` int NULL DEFAULT NULL COMMENT '后区奇数个数',
  `back_even_count` int NULL DEFAULT NULL COMMENT '后区偶数个数',
  `back_span` int NULL DEFAULT NULL COMMENT '后区跨度',
  `back_summation` int NULL DEFAULT NULL COMMENT '后区和值',
  `back_summation_tail` int NULL DEFAULT NULL COMMENT '后区和值尾数',
  `back_small_count` int NULL DEFAULT NULL COMMENT '后区小数个数（1-6为小，7-12为大）',
  `back_big_count` int NULL DEFAULT NULL COMMENT '后区大数个数',
  `back_repeat_count` int NULL DEFAULT NULL COMMENT '与上期后区重复个数',
  `back_repeat_flag_front` tinyint NULL DEFAULT 0 COMMENT '后区号码是否与前区重复',
  `total_summation` int NULL DEFAULT NULL COMMENT '总合值（前区和+后区和）',
  `total_odd_count` int NULL DEFAULT NULL COMMENT '整体奇数个数',
  `total_even_count` int NULL DEFAULT NULL COMMENT '整体偶数个数',
  `special_pattern` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '特殊形态（全奇、全偶、全小、全大、断区等）',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `uk_issue_num`(`issue_num` ASC) USING BTREE,
  INDEX `idx_draw_date`(`draw_date` ASC) USING BTREE,
  INDEX `idx_front_summation`(`front_summation` ASC) USING BTREE,
  INDEX `idx_back_one`(`back_one` ASC) USING BTREE,
  INDEX `idx_back_two`(`back_two` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 2889 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '大乐透历史开奖结果表' ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- Table structure for ssq_all
-- ----------------------------
DROP TABLE IF EXISTS `ssq_all`;
CREATE TABLE `ssq_all`  (
  `id` bigint UNSIGNED NOT NULL AUTO_INCREMENT COMMENT 'id',
  `red_one` int NULL DEFAULT NULL COMMENT '红球1',
  `red_two` int NULL DEFAULT NULL COMMENT '红球2',
  `red_three` int NULL DEFAULT NULL COMMENT '红球3',
  `red_four` int NULL DEFAULT NULL COMMENT '红球4',
  `red_five` int NULL DEFAULT NULL COMMENT '红球5',
  `red_six` int NULL DEFAULT NULL COMMENT '红球6',
  `blue_one` int NULL DEFAULT NULL COMMENT '篮球1',
  PRIMARY KEY (`id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 17721089 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '双色球全部' ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- Table structure for ssq_forecast
-- ----------------------------
DROP TABLE IF EXISTS `ssq_forecast`;
CREATE TABLE `ssq_forecast`  (
  `id` int NOT NULL AUTO_INCREMENT,
  `forecast_date` date NOT NULL,
  `group_id` int NOT NULL DEFAULT 1,
  `red_one` int NOT NULL,
  `red_two` int NOT NULL,
  `red_three` int NOT NULL,
  `red_four` int NOT NULL,
  `red_five` int NOT NULL,
  `red_six` int NOT NULL,
  `blue_one` int NOT NULL,
  `model_version` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT 'LSTM_Attention',
  `create_time` datetime NULL DEFAULT CURRENT_TIMESTAMP,
  `quality_score` float NULL DEFAULT NULL,
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_forecast_date`(`forecast_date` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 9 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '双色球预测' ROW_FORMAT = DYNAMIC;

-- ----------------------------
-- Table structure for ssq_history
-- ----------------------------
DROP TABLE IF EXISTS `ssq_history`;
CREATE TABLE `ssq_history`  (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `issue_num` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '期号（如2025001）',
  `draw_date` date NOT NULL COMMENT '开奖日期',
  `weekday` varchar(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '星期几',
  `year` int NULL DEFAULT NULL COMMENT '年份',
  `month` int NULL DEFAULT NULL COMMENT '月份',
  `quarter` int NULL DEFAULT NULL COMMENT '季度',
  `red_one` int NOT NULL COMMENT '红球1',
  `red_two` int NOT NULL COMMENT '红球2',
  `red_three` int NOT NULL COMMENT '红球3',
  `red_four` int NOT NULL COMMENT '红球4',
  `red_five` int NOT NULL COMMENT '红球5',
  `red_six` int NOT NULL COMMENT '红球6',
  `blue_one` int NOT NULL COMMENT '蓝球',
  `red_max` int NULL DEFAULT NULL COMMENT '红球最大值',
  `red_min` int NULL DEFAULT NULL COMMENT '红球最小值',
  `red_span` int NULL DEFAULT NULL COMMENT '红球跨度（max-min）',
  `red_summation` int NULL DEFAULT NULL COMMENT '红球和值',
  `red_summation_tail` int NULL DEFAULT NULL COMMENT '和值尾数',
  `red_odd_count` int NULL DEFAULT NULL COMMENT '红球奇数个数',
  `red_even_count` int NULL DEFAULT NULL COMMENT '红球偶数个数',
  `red_small_count` int NULL DEFAULT NULL COMMENT '红球小数个数（1-16为小，17-33为大）',
  `red_big_count` int NULL DEFAULT NULL COMMENT '红球大数个数',
  `red_prime_count` int NULL DEFAULT NULL COMMENT '红球质数个数',
  `red_composite_count` int NULL DEFAULT NULL COMMENT '红球合数个数',
  `red_mod0_count` int NULL DEFAULT NULL COMMENT '除3余0个数',
  `red_mod1_count` int NULL DEFAULT NULL COMMENT '除3余1个数',
  `red_mod2_count` int NULL DEFAULT NULL COMMENT '除3余2个数',
  `red_zone1_count` int NULL DEFAULT NULL COMMENT '一区个数（1-11）',
  `red_zone2_count` int NULL DEFAULT NULL COMMENT '二区个数（12-22）',
  `red_zone3_count` int NULL DEFAULT NULL COMMENT '三区个数（23-33）',
  `red_consecutive_groups` int NULL DEFAULT NULL COMMENT '连号组数',
  `red_consecutive_max_len` int NULL DEFAULT NULL COMMENT '最大连号长度',
  `red_repeat_count` int NULL DEFAULT NULL COMMENT '与上期红球重复个数',
  `red_ac_value` int NULL DEFAULT NULL COMMENT 'AC值（算术复杂性）',
  `red_first_last_sum` int NULL DEFAULT NULL COMMENT '首尾和',
  `red_middle_avg` decimal(5, 2) NULL DEFAULT NULL COMMENT '红球均值',
  `red_std_dev` decimal(8, 4) NULL DEFAULT NULL COMMENT '红球标准差',
  `blue_odd_even` varchar(4) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '蓝球奇偶（odd/even）',
  `blue_size` varchar(4) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '蓝球大小（1-8小，9-16大）',
  `blue_mod3` int NULL DEFAULT NULL COMMENT '蓝球除3余数（0/1/2）',
  `blue_mod4` int NULL DEFAULT NULL COMMENT '蓝球除4余数',
  `blue_repeat_flag` tinyint(1) NULL DEFAULT 0 COMMENT '是否与上期蓝球重复',
  `total_sum` int NULL DEFAULT NULL COMMENT '整体和值（红球和值+蓝球）',
  `total_odd_count` int NULL DEFAULT NULL COMMENT '整体奇数个数',
  `total_even_count` int NULL DEFAULT NULL COMMENT '整体偶数个数',
  `total_small_count` int NULL DEFAULT NULL COMMENT '整体小数个数',
  `total_big_count` int NULL DEFAULT NULL COMMENT '整体大数个数',
  `special_pattern` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL DEFAULT NULL COMMENT '特殊形态（全奇、全偶、全小、全大、断区等）',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `uk_issue_num`(`issue_num` ASC) USING BTREE,
  INDEX `idx_draw_date`(`draw_date` ASC) USING BTREE,
  INDEX `idx_blue_one`(`blue_one` ASC) USING BTREE,
  INDEX `idx_red_summation`(`red_summation` ASC) USING BTREE,
  INDEX `idx_red_span`(`red_span` ASC) USING BTREE,
  INDEX `idx_special_pattern`(`special_pattern` ASC) USING BTREE,
  INDEX `idx_year_month`(`year` ASC, `month` ASC) USING BTREE,
  INDEX `idx_red_one`(`red_one` ASC) USING BTREE,
  INDEX `idx_red_two`(`red_two` ASC) USING BTREE,
  INDEX `idx_red_three`(`red_three` ASC) USING BTREE,
  INDEX `idx_red_four`(`red_four` ASC) USING BTREE,
  INDEX `idx_red_five`(`red_five` ASC) USING BTREE,
  INDEX `idx_red_six`(`red_six` ASC) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 1975 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '双色球历史开奖结果表' ROW_FORMAT = DYNAMIC;

SET FOREIGN_KEY_CHECKS = 1;
