#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
无限循环随机训练脚本：每轮随机生成训练参数（彩种/epochs/batch_size/seq_len/学习率），
提交成功立即提交下一个（不等训练结果），失败自动重试，提交记录追加保存到 CSV。

特性：
- 启动时先调用 fetch_ssq_incremental / fetch_dlt_incremental 增量更新数据（无新数据直接跳过）
- 无限循环、参数全随机、提交失败自动重试（最多3次）
- 自动获取数据库总记录数，避免提交超限的 seq_len
- CSV 记录提交参数和 task_id，训练结果由 Worker 落盘 models/ 目录
"""

import csv
import math
import os
import random
import sys
import time
from pathlib import Path

import pymysql
import requests

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 导入配置
from app.core.config import settings

BASE_URL = "http://localhost:8000"          # API 地址
MAX_RETRIES = 3                             # 最大重试次数
RETRY_DELAY = 2                             # 重试间隔（秒）
REQUEST_TIMEOUT = 30                        # 请求超时时间（秒）
RESULT_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "batch_train_results.csv")
ROUND_DELAY = 30                            # 每轮提交之间的间隔（秒）
FETCH_INTERVAL = 6 * 3600                    # 增量抓取间隔（秒）：每 6 小时重新抓取一次，让持续运行的脚本也能滚动获取新期开奖数据

# ==================== 随机参数范围（深度搜索） ====================
LOTTERY_TYPES = ["ssq", "dlt"]              # 彩种候选：ssq/dlt
EPOCHS_RANGE = (50, 200)                    # 训练轮数范围（充分训练，配合早停）
BATCH_SIZES = [16, 32, 64, 128, 256]        # 批次大小候选（全覆盖）
LR_MIN, LR_MAX = 0.00001, 0.00005           # 学习率范围（对数均匀采样，全覆盖）

with_fetch = False                          # 不抓取数据（数据已存在）

# ==================== 获取数据库总记录数 ====================
def get_total_count(lottery_type):
    """查询数据库中对应彩种的历史记录总数"""
    conn = pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DATABASE
    )
    cursor = conn.cursor()
    table = 'ssq_history' if lottery_type == 'ssq' else 'dlt_history'
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]
    conn.close()
    return count

# ==================== 生成随机训练参数 ====================
def generate_random_params(total_map, hyperparams_map=None):
    """生成一轮随机训练参数。

    P2 超参元学习：hyperparams_map 非空时 70% 概率从高命中率超参区间采样（偏向），
    30% 全随机（探索）；hyperparams_map 为空或对应彩种无数据时退化为全随机。
    """
    lottery_type = random.choice(LOTTERY_TYPES)

    # P2 超参元学习：偏向高命中率区间
    hp = (hyperparams_map or {}).get(lottery_type)
    use_bias = hp is not None and random.random() < 0.7

    # epochs
    if use_bias and hp.get("epochs_range"):
        ep_low, ep_high = hp["epochs_range"]
        epochs = random.randint(min(ep_low, ep_high), max(ep_low, ep_high))
    else:
        epochs = random.randint(*EPOCHS_RANGE)

    # batch_size
    if use_bias and hp.get("batch_sizes"):
        batch_size = random.choice(hp["batch_sizes"])
    else:
        batch_size = random.choice(BATCH_SIZES)

    # learning_rate（对数均匀采样）
    if use_bias and hp.get("lr_log_range"):
        lr_low, lr_high = hp["lr_log_range"]
        learning_rate = 10 ** random.uniform(math.log10(lr_low), math.log10(lr_high))
    else:
        learning_rate = 10 ** random.uniform(math.log10(LR_MIN), math.log10(LR_MAX))

    # 每轮随机 seed，避免所有模型初始化权重相同导致预测趋同
    seed = random.randint(1, 2147483647)
    # seq_len：取最大值（trainer 会自动保护 MIN_SAMPLES=200）
    total = total_map[lottery_type]
    seq_len = total - 1
    return {
        "lottery_type": lottery_type,
        "epochs": epochs,
        "batch_size": batch_size,
        "seq_len": seq_len,
        "learning_rate": learning_rate,
        "seed": seed,
        "with_fetch": with_fetch
    }

# ==================== 提交任务函数（带重试） ====================
def submit_task(payload):
    """提交单个训练任务，失败时自动重试"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(
                f"{BASE_URL}/train/start",
                json=payload,
                timeout=REQUEST_TIMEOUT
            )
            if resp.status_code == 200:
                data = resp.json()
                task_id = data.get("task_id")
                print(f"   ✅ 任务已提交: {task_id}")
                return task_id
            else:
                print(f"   ⚠️ 提交失败 (状态码 {resp.status_code})，尝试 {attempt}/{MAX_RETRIES}")
        except requests.exceptions.RequestException as e:
            print(f"   ⚠️ 请求异常: {e}，尝试 {attempt}/{MAX_RETRIES}")

        # 最后一次重试失败则放弃
        if attempt == MAX_RETRIES:
            print(f"   ❌ 放弃本轮任务（已达最大重试次数）: {payload}")
            return None

        time.sleep(RETRY_DELAY)

# ==================== 追加保存提交记录到 CSV ====================
def append_result(params, status, task_id=""):
    """追加一行提交记录到 CSV（文件不存在时先写表头）"""
    new_file = not os.path.exists(RESULT_CSV)

    with open(RESULT_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow([
            "lottery_type", "epochs", "batch_size", "seq_len",
            "learning_rate", "seed", "status",
            "best_val_loss", "best_epoch",
            "final_train_loss", "final_val_loss",
            "input_dim", "run_id"
        ])
        writer.writerow([
            params["lottery_type"], params["epochs"], params["batch_size"],
            params["seq_len"], params["learning_rate"], params.get("seed", ""),
            status,
            "", "", "", "", "",
            task_id
        ])

# ==================== 数据增量更新 ====================
def run_fetch_scripts():
    """调用增量抓取脚本更新数据（无新数据或失败时直接跳过，继续提交训练）"""
    from app.scripts.fetch_ssq_incremental import main as fetch_ssq
    from app.scripts.fetch_dlt_incremental import main as fetch_dlt

    for name, fn in [("双色球 (ssq)", fetch_ssq), ("大乐透 (dlt)", fetch_dlt)]:
        print(f"\n📥 开始增量抓取: {name} ...")
        try:
            fn()
        except Exception as e:
            print(f"⚠️ {name} 抓取失败（忽略并继续）: {e}")

# ==================== 启动检查 ====================
print("=" * 60)
print("🚀 无限循环随机训练（提交即走，不等结果）")
print(f"   彩种候选: {LOTTERY_TYPES}")
print(f"   训练轮数范围: {EPOCHS_RANGE}")
print(f"   批次大小候选: {BATCH_SIZES}")
print(f"   学习率范围: {LR_MIN} ~ {LR_MAX}")
print(f"   seq_len: 取最大值（trainer 自动保护 MIN_SAMPLES=200）")
print(f"   提交间隔: {ROUND_DELAY} 秒")
print(f"   提交记录: {RESULT_CSV}（追加）")
print("=" * 60)

# 先执行增量抓取更新数据，无新数据时直接进入训练
run_fetch_scripts()
last_fetch_time = time.time()

# 过滤掉数据量不足的彩种（抓取后统计，包含最新数据）
total_map = {}
for lt in list(LOTTERY_TYPES):
    total = get_total_count(lt)
    if total < 2:
        print(f"⚠️ {lt} 数据太少（{total} 条），跳过该彩种")
        LOTTERY_TYPES.remove(lt)
    else:
        total_map[lt] = total
        print(f"📊 {lt.upper()} 总记录数: {total}，最大可用 seq_len: {total - 1}")

if not LOTTERY_TYPES:
    print("❌ 没有可用彩种，退出。")
    sys.exit(1)

# ==================== 无限循环提交 ====================
round_no = 0
while True:
    round_no += 1

    # 滚动数据更新：距上次抓取超过 FETCH_INTERVAL 则重新抓取，让新期开奖数据进入训练集
    if time.time() - last_fetch_time > FETCH_INTERVAL:
        print(f"\n🔄 第 {round_no} 轮前检测到距上次抓取已超过 {FETCH_INTERVAL // 3600} 小时，重新增量抓取...")
        run_fetch_scripts()
        # 抓取后刷新 total_map（新数据可能增加可用 seq_len）
        for lt in LOTTERY_TYPES:
            total_map[lt] = get_total_count(lt)
            print(f"📊 {lt.upper()} 最新记录数: {total_map[lt]}，最大可用 seq_len: {total_map[lt] - 1}")
        last_fetch_time = time.time()

    # P2 超参元学习：获取高命中率模型的超参区间（内部缓存 1 小时）
    hyperparams_map = {}
    try:
        from app.services.backtest_service import get_top_hyperparams
        for lt in LOTTERY_TYPES:
            hp = get_top_hyperparams(lt)
            if hp:
                hyperparams_map[lt] = hp
        if hyperparams_map:
            print(f"🎯 超参偏向采样：{list(hyperparams_map.keys())}")
    except Exception as e:
        print(f"⚠️ 获取超参区间失败（回退全随机）: {e}")

    params = generate_random_params(total_map, hyperparams_map)

    print(f"\n🔄 第 {round_no} 轮 | 彩种: {params['lottery_type']} | epochs: {params['epochs']} | "
          f"batch_size: {params['batch_size']} | seq_len: {params['seq_len']} | "
          f"lr: {params['learning_rate']:.8f} | seed: {params['seed']}")

    task_id = submit_task(params)
    if task_id:
        # 提交成功，记录后立即进入下一轮，不等训练结果
        append_result(params, "submitted", task_id)
    else:
        append_result(params, "failed_submit")

    time.sleep(ROUND_DELAY)
