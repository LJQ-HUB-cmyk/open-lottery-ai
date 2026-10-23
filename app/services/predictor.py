# -*- coding: utf-8 -*-
"""
预测服务：加载分类模型，基于概率分布选号，存入数据库。

核心改进（vs 旧版回归预测）：
- 从模型输出 logits → sigmoid → 概率分布
- 红球取 Top-K 概率号码，蓝球取 Top-1/2
- 基于概率的加权质量评分
- 兼容旧模型（meta 中无 model_type 时走回归逻辑，但 data_loader 已升级会报错）
"""
import asyncio
import json
import os
import threading
import zlib
from collections import OrderedDict
from datetime import date

import joblib
import numpy as np
import torch
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.dlt_forecast import DLTForecast
from app.models.ssq_forecast import SSQForecast
from app.services.analysis_service import get_next_draw_date, is_draw_day
from .data_loader import (
    load_ssq_data, load_dlt_data,
    SSQ_FEATURE_COLS, SSQ_TARGET_COLS,
    DLT_FEATURE_COLS, DLT_TARGET_COLS,
    SSQ_RED_RANGE, SSQ_BLUE_RANGE,
    DLT_FRONT_RANGE, DLT_BACK_RANGE,
)
from .transformer_model import LotteryClassifier

# 推理服务进程（FastAPI）内每个推理只跑单线程，靠 16 路 worker 并发吃满 CPU；
# 否则多个推理各自占满全部核会造成线程超订。注意：训练在独立 Celery 进程，
# 不 import 本模块，故该进程级设置不会影响训练。
torch.set_num_threads(1)


def _stable_seed(text: str) -> int:
    """基于字符串生成稳定种子（crc32，不受 PYTHONHASHSEED 影响，跨重启/跨进程一致）"""
    return zlib.crc32(text.encode('utf-8')) & 0x7FFFFFFF


def _select_topk_deterministic(probs: np.ndarray, k: int, upper: int) -> list:
    """
    概率 Top-K 确定性选号（1-based，升序返回）。
    与训练验证 / 回测 / 集成口径完全一致，保证可复现、评分与选号统一。
    """
    p = np.asarray(probs, dtype=np.float64)[:upper]
    idx = np.argsort(-p)[:k]
    return sorted(int(i) + 1 for i in idx)


def _load_meta(save_dir: str, lottery_type: str, model_name: str) -> dict:
    """加载模型 meta 文件（带 LRU 缓存）"""
    if model_name.endswith('_final.pt'):
        meta_path = os.path.join(save_dir, f"{lottery_type}_final_meta.json")
    else:
        run_id = os.path.splitext(model_name)[0]
        meta_path = os.path.join(save_dir, f"{run_id}_meta.json")

    key = (meta_path, os.path.getmtime(meta_path)) if os.path.exists(meta_path) else None
    if key is not None:
        cached = _META_CACHE.get(key)
        if cached is not None:
            _META_CACHE.move_to_end(key)
            return cached

    if os.path.exists(meta_path):
        with open(meta_path, 'r', encoding='utf-8') as f:
            meta = json.load(f)
        if key is not None:
            with _CACHE_LOCK:
                _META_CACHE[key] = meta
                _META_CACHE.move_to_end(key)
                while len(_META_CACHE) > _META_CACHE_MAX:
                    _META_CACHE.popitem(last=False)
        return meta
    return {}


# 模型/标准化器/meta 缓存：key=(文件路径, mtime)，文件被覆盖重训时自动失效。
# 有界 LRU：模型可达数千个，全量常驻会 OOM，超出上限淘汰最久未用项。
_MODEL_CACHE = OrderedDict()
_SCALER_CACHE = OrderedDict()
_META_CACHE = OrderedDict()
_MODEL_CACHE_MAX = 256       # 权重单个数 MB，严格封顶
_SCALER_CACHE_MAX = 512      # StandardScaler 很小
_META_CACHE_MAX = 2048       # meta 为小 dict
# 缓存填充锁：批量并行推理时多线程同时加载同一模型，用双重检查避免重复 torch.load
_CACHE_LOCK = threading.Lock()


def _load_model_cached(model_path: str, meta: dict, num_red: int, num_blue: int, input_dim_fallback: int):
    """加载分类模型（带 LRU 缓存，避免每次预测重复 torch.load + 重建网络）"""
    key = (model_path, os.path.getmtime(model_path))
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        _MODEL_CACHE.move_to_end(key)
        return cached

    with _CACHE_LOCK:
        # 双重检查：可能在等待锁期间已被其他线程加载
        cached = _MODEL_CACHE.get(key)
        if cached is not None:
            _MODEL_CACHE.move_to_end(key)
            return cached
        model = LotteryClassifier(
            input_dim=meta.get("input_dim", input_dim_fallback),
            d_model=meta.get("d_model", 128),
            nhead=meta.get("nhead", 4),
            num_layers=meta.get("num_layers", 3),
            num_red=num_red,
            num_blue=num_blue,
            dropout=meta.get("dropout", 0.15),
        )
        model.load_state_dict(torch.load(model_path, map_location='cpu', weights_only=False))
        model.eval()
        _MODEL_CACHE[key] = model
        while len(_MODEL_CACHE) > _MODEL_CACHE_MAX:
            _MODEL_CACHE.popitem(last=False)
        return model


def _load_scaler_cached(scaler_path: str):
    """加载标准化器（带 LRU 缓存）"""
    key = (scaler_path, os.path.getmtime(scaler_path))
    cached = _SCALER_CACHE.get(key)
    if cached is not None:
        _SCALER_CACHE.move_to_end(key)
        return cached

    with _CACHE_LOCK:
        cached = _SCALER_CACHE.get(key)
        if cached is not None:
            _SCALER_CACHE.move_to_end(key)
            return cached
        scaler = joblib.load(scaler_path)
        _SCALER_CACHE[key] = scaler
        while len(_SCALER_CACHE) > _SCALER_CACHE_MAX:
            _SCALER_CACHE.popitem(last=False)
        return scaler


def _lottery_config(lottery_type):
    """
    返回彩种的数据加载与号码规则配置。
    """
    if lottery_type == 'ssq':
        return {
            "feature_cols": SSQ_FEATURE_COLS, "target_cols": SSQ_TARGET_COLS,
            "num_red": SSQ_RED_RANGE, "num_blue": SSQ_BLUE_RANGE,
            "red_pick": 6, "blue_pick": 1, "red_upper": 33, "blue_upper": 16,
        }
    return {
        "feature_cols": DLT_FEATURE_COLS, "target_cols": DLT_TARGET_COLS,
        "num_red": DLT_FRONT_RANGE, "num_blue": DLT_BACK_RANGE,
        "red_pick": 5, "blue_pick": 2, "red_upper": 35, "blue_upper": 12,
    }


def _resolve_model_paths(lottery_type, model_name):
    """
    解析模型文件、标准化器文件路径与入库用模型名。
    """
    save_dir = os.path.join(settings.MODEL_SAVE_DIR, lottery_type)
    if model_name:
        if not model_name.endswith('.pt'):
            model_name = model_name + '.pt'
        model_path = os.path.join(save_dir, model_name)
        scaler_path = os.path.join(save_dir, model_name.replace('.pt', '_scaler.joblib'))
        if not os.path.exists(scaler_path):
            scaler_path = os.path.join(save_dir, f"{lottery_type}_scaler.joblib")
    else:
        model_name = f"{lottery_type}_final.pt"
        model_path = os.path.join(save_dir, model_name)
        scaler_path = os.path.join(save_dir, f"{lottery_type}_scaler.joblib")

    if not os.path.exists(model_path):
        raise FileNotFoundError(f"模型文件 {model_path} 不存在，请先训练模型")
    if not os.path.exists(scaler_path):
        raise FileNotFoundError(f"标准化器文件 {scaler_path} 不存在")
    return save_dir, model_path, scaler_path, model_name


def _infer_sync(lottery_type, model_name, df, cfg):
    """
    单模型同步推理（CPU 密集，供 asyncio.to_thread 在线程池并行调用）。
    不访问数据库，返回选号与质量评分。
    """
    save_dir, model_path, scaler_path, model_file = _resolve_model_paths(lottery_type, model_name)
    feature_cols, target_cols = cfg["feature_cols"], cfg["target_cols"]
    num_red, num_blue = cfg["num_red"], cfg["num_blue"]
    red_pick, blue_pick = cfg["red_pick"], cfg["blue_pick"]
    red_upper, blue_upper = cfg["red_upper"], cfg["blue_upper"]

    meta = _load_meta(save_dir, lottery_type, model_file)
    if meta.get("model_type", "regression") != "classifier":
        raise RuntimeError("检测到旧版回归模型，请删除旧模型文件后重新训练")

    feature_dim = len(feature_cols)
    seq_len = meta.get("pred_seq_len", 30)
    last_seq = df.values[-seq_len:]

    features = last_seq[:, :feature_dim].astype(np.float32)
    targets_raw = last_seq[:, feature_dim:].astype(np.float32)
    scaler = _load_scaler_cached(scaler_path)
    scaled_features = scaler.transform(features)
    scaled_seq = np.concatenate([scaled_features, targets_raw], axis=1)
    input_tensor = torch.tensor(scaled_seq, dtype=torch.float32).unsqueeze(0)

    input_dim = meta.get("input_dim", feature_dim + len(target_cols))
    model = _load_model_cached(model_path, meta, num_red, num_blue, input_dim)

    with torch.no_grad():
        logits = model(input_tensor).squeeze().numpy()
    probs = 1.0 / (1.0 + np.exp(-logits))
    red_probs = probs[:num_red]
    blue_probs = probs[num_red:]

    # 确定性 Top-K 选号（与训练验证/回测/集成一致，可复现）
    reds = _select_topk_deterministic(red_probs, red_pick, red_upper)
    blues = _select_topk_deterministic(blue_probs, blue_pick, blue_upper)

    # 兜底（理论上 upper>=pick 不会触发）：用稳定种子随机补足，避免任何不可复现
    rng = np.random.RandomState(_stable_seed(model_file))
    while len(reds) < red_pick:
        candidates = [x for x in range(1, red_upper + 1) if x not in reds]
        reds.append(int(rng.choice(candidates)))
    reds = sorted(reds)

    if lottery_type == 'dlt':
        while len(blues) < blue_pick:
            candidates = [x for x in range(1, blue_upper + 1) if x not in blues]
            blues.append(int(rng.choice(candidates)))
        blues = sorted(blues)
    else:
        blues = blues[:blue_pick]

    # 质量评分基于"实际选中号码"的概率，保证评分与选号一致
    red_sel = red_probs[[r - 1 for r in reds]]
    blue_sel = blue_probs[[b - 1 for b in blues]]
    avg_prob = float(np.mean(red_sel) * 0.7 + np.mean(blue_sel) * 0.3)
    quality_score = round(float(np.clip(avg_prob, 0, 1) * 0.9 + 0.1), 3)

    return {"red": reds, "blue": blues, "quality_score": quality_score, "model_name": model_file}


def _get_target_date(lottery_type):
    """
    计算预测对应的目标开奖日期。
    """
    today = date.today()
    if is_draw_day(lottery_type, today):
        return today
    target = get_next_draw_date(lottery_type, today)
    if target is None:
        raise ValueError(f"无法找到 {lottery_type} 的下一个开奖日")
    return target


def _apply_numbers(row, reds, blues, qs, lottery_type):
    """把号码与评分写入一行 forecast（更新已存在行时复用，避免赋值逻辑重复）"""
    row.red_one, row.red_two, row.red_three = reds[0], reds[1], reds[2]
    row.red_four, row.red_five = reds[3], reds[4]
    row.blue_one = blues[0]
    row.quality_score = qs
    if lottery_type == 'ssq':
        row.red_six = reds[5]
    else:
        row.blue_two = blues[1]


async def _bulk_upsert_forecasts(lottery_type, target_date, items):
    """
    批量 upsert 预测记录：一次查询目标日期全部已有记录，内存匹配后批量插入/更新，单次 commit。
    避免逐条 SELECT 造成的 N 次数据库往返。返回 {model_name: "插入"/"更新"}。
    """
    model_cls = SSQForecast if lottery_type == 'ssq' else DLTForecast
    actions = {}
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(model_cls).where(model_cls.forecast_date == target_date)
        )).scalars().all()
        existing = {r.model_version: r for r in rows}

        for item in items:
            name, reds, blues, qs = (
                item["model_name"], item["red"], item["blue"], item["quality_score"])
            row = existing.get(name)
            if row is not None:
                _apply_numbers(row, reds, blues, qs, lottery_type)
                actions[name] = "更新"
            else:
                if lottery_type == 'ssq':
                    row = SSQForecast(
                        forecast_date=target_date, group_id=1,
                        red_one=reds[0], red_two=reds[1], red_three=reds[2],
                        red_four=reds[3], red_five=reds[4], red_six=reds[5],
                        blue_one=blues[0], model_version=name, quality_score=qs)
                else:
                    row = DLTForecast(
                        forecast_date=target_date, group_id=1,
                        red_one=reds[0], red_two=reds[1], red_three=reds[2],
                        red_four=reds[3], red_five=reds[4],
                        blue_one=blues[0], blue_two=blues[1],
                        model_version=name, quality_score=qs)
                db.add(row)
                actions[name] = "插入"
        await db.commit()
    return actions


async def get_prediction(lottery_type, model_version="latest", model_name=None):
    """
    基于分类模型生成预测，保存到预测表。
    """
    cfg = _lottery_config(lottery_type)
    df = await (load_ssq_data() if lottery_type == 'ssq' else load_dlt_data())
    if df is None or len(df) < 30:
        raise ValueError(f"数据不足，至少需要 30 条历史数据，当前 {0 if df is None else len(df)} 条")

    # torch 推理为 CPU 密集操作，丢线程池避免阻塞事件循环
    pred = await asyncio.to_thread(_infer_sync, lottery_type, model_name, df, cfg)
    reds, blues = pred["red"], pred["blue"]
    quality_score, model_file = pred["quality_score"], pred["model_name"]

    target_date = _get_target_date(lottery_type)
    # 复用批量 upsert（单条场景），避免维护两套入库逻辑
    actions = await _bulk_upsert_forecasts(
        lottery_type, target_date,
        [{"model_name": model_file, "red": reds, "blue": blues,
          "quality_score": quality_score}])
    action = actions.get(model_file, "插入")

    return {
        "red": reds,
        "blue": blues,
        "quality_score": quality_score,
        "model_version": model_file,
        "action": action,
        "model_name": model_file,
        "forecast_date": target_date.strftime("%Y-%m-%d")
    }


async def iter_predictions_batch(lottery_type, model_names, max_workers=4):
    """
    批量并行预测的流式版本（异步生成器）：数据只加载一次，多模型在线程池并行推理，
    每完成一个模型立即 yield 一条进度事件，全部完成后单会话批量入库。

    事件序列：
      {"type": "start", "total": N, "forecast_date": "..."}
      {"type": "progress", "done": k, "total": N, "model_name": ..., "success": True/False, ...}
      {"type": "done", "success_count": a, "failed_count": b, "forecast_date": "..."}
      出错时：{"type": "error", "error": "..."}
    """
    cfg = _lottery_config(lottery_type)
    df = await (load_ssq_data() if lottery_type == 'ssq' else load_dlt_data())
    if df is None or len(df) < 30:
        yield {"type": "error",
               "error": f"数据不足，至少需要 30 条历史数据，当前 {0 if df is None else len(df)} 条"}
        return

    target_date = _get_target_date(lottery_type)
    yield {"type": "start", "total": len(model_names),
           "forecast_date": target_date.strftime("%Y-%m-%d")}

    sem = asyncio.Semaphore(max_workers)

    async def _infer_one(name):
        # 线程池并行推理；异常在内部捕获并携带模型名返回，供 as_completed 逐条上报
        async with sem:
            try:
                item = await asyncio.to_thread(_infer_sync, lottery_type, name, df, cfg)
                return name, item, None
            except Exception as e:  # noqa: BLE001
                return name, None, e

    tasks = [asyncio.ensure_future(_infer_one(n)) for n in model_names]
    ok_items, failed = [], []
    done_count = 0
    for coro in asyncio.as_completed(tasks):
        name, item, err = await coro
        done_count += 1
        if err is not None:
            failed.append({"model_name": name, "error": str(err)})
            yield {"type": "progress", "done": done_count, "total": len(model_names),
                   "model_name": name, "success": False, "error": str(err)}
        else:
            ok_items.append(item)
            yield {"type": "progress", "done": done_count, "total": len(model_names),
                   "model_name": item["model_name"], "success": True,
                   "red": item["red"], "blue": item["blue"],
                   "quality_score": item["quality_score"]}

    # 批量 upsert：一次查询 + 单次 commit（数千模型时避免 N 次数据库往返）
    if ok_items:
        await _bulk_upsert_forecasts(lottery_type, target_date, ok_items)

    # 预测入库后自动生成复试方案（同一目标开奖日，复用当期预测频率池）
    fushi_info = await _auto_generate_fushi(lottery_type, target_date)

    yield {"type": "done", "total": len(model_names),
           "success_count": len(ok_items), "failed_count": len(failed),
           "forecast_date": target_date.strftime("%Y-%m-%d"),
           "fushi": fushi_info}


async def _auto_generate_fushi(lottery_type: str, forecast_date: date) -> dict:
    """批量预测入库后自动生成复试方案并写库，失败不影响预测主流程。"""
    try:
        from app.services.fushi_service import generate_fushi
        result = await generate_fushi(lottery_type, forecast_date)
        if result.get("skipped"):
            return {"skipped": True, "message": result.get("message", "")}
        return {
            "skipped": False,
            "patterns_total": result.get("patterns_total", 0),
            "generated": len(result.get("plans", [])),
        }
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ 复试自动生成失败（{lottery_type} {forecast_date}）: {type(e).__name__}: {e}")
        return {"skipped": True, "message": f"复试生成失败: {type(e).__name__}: {e}"}


async def get_predictions_batch(lottery_type, model_names, max_workers=4):
    """
    批量并行预测（一次性返回）：消费 iter_predictions_batch 事件流，汇总为结果字典。
    返回成功/失败明细，供一键预测与批量按钮使用。
    """
    results, failed = [], []
    forecast_date = None
    async for evt in iter_predictions_batch(lottery_type, model_names, max_workers=max_workers):
        if evt["type"] == "error":
            raise ValueError(evt["error"])
        if evt["type"] == "start":
            forecast_date = evt["forecast_date"]
        elif evt["type"] == "progress":
            if evt["success"]:
                results.append({
                    "model_name": evt["model_name"],
                    "red": evt["red"], "blue": evt["blue"],
                    "quality_score": evt["quality_score"],
                })
            else:
                failed.append({"model_name": evt["model_name"], "error": evt["error"]})
        elif evt["type"] == "done":
            forecast_date = evt["forecast_date"]

    return {
        "lottery_type": lottery_type,
        "forecast_date": forecast_date,
        "total": len(model_names),
        "success_count": len(results),
        "failed_count": len(failed),
        "results": results,
        "failed": failed,
    }
