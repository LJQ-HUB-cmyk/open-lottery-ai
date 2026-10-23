# -*- coding: utf-8 -*-
import json
import logging
import os
import traceback
from typing import List, Dict, Any

import httpx
import numpy as np
from openai import OpenAI
from sentence_transformers import SentenceTransformer
from sqlalchemy import select, desc

# 嵌入模型仅使用本地缓存，禁止 HuggingFace 在线下载（模型未缓存时联网会无限期卡死）
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from app.core.agent_templates import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from app.core.config import settings
from app.core.database import SyncSessionLocal
from app.models.dlt_forecast import DLTForecast
from app.models.ssq_forecast import SSQForecast

logger = logging.getLogger(__name__)


def _llm_configured() -> bool:
    """判断大模型是否真正可用（排除空值与占位符 key）"""
    key = (getattr(settings, "DEEPSEEK_API_KEY", "") or "").strip()
    if not key or "your-deepseek" in key.lower() or key.lower() in ("changeme", "none"):
        return False
    return True

class AgentService:
    _embedding_model = None
    _llm_client = None
    # 大模型认证失败熔断：key 无效(401/403)后置 True，后续请求直接本地兜底，不再白等加载/调用
    _llm_auth_failed = False

    @classmethod
    def _get_embedding_model(cls):
        if cls._embedding_model is None:
            logger.info(f"加载嵌入模型: {settings.EMBEDDING_MODEL_NAME}")
            cls._embedding_model = SentenceTransformer(settings.EMBEDDING_MODEL_NAME)
        return cls._embedding_model

    @classmethod
    def _get_llm_client(cls):
        if cls._llm_client is None:
            if not settings.DEEPSEEK_API_KEY:
                raise ValueError("DEEPSEEK_API_KEY 未配置，无法使用大模型")
            http_client = httpx.Client(timeout=25.0, follow_redirects=True)
            cls._llm_client = OpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                http_client=http_client,
            )
        return cls._llm_client

    @classmethod
    def _get_embedding(cls, text: str) -> np.ndarray:
        model = cls._get_embedding_model()
        return model.encode(text, normalize_embeddings=True)

    @classmethod
    def _fetch_historical_tasks(cls, lottery_type: str) -> List[Dict[str, Any]]:
        """从数据库获取已完成的历史训练任务（基于预测记录反向推断）"""
        # 由于没有专门的训练任务表，我们用预测记录中的 model_version 和 quality_score 来代表历史训练结果
        # 同时查询历史数据量作为参考
        with SyncSessionLocal() as session:
            # 查询该彩种所有预测记录，按模型版本分组，取最高质量评分
            if lottery_type == 'ssq':
                stmt = select(SSQForecast).where(
                    SSQForecast.model_version.isnot(None)
                ).order_by(desc(SSQForecast.create_time))
            else:
                stmt = select(DLTForecast).where(
                    DLTForecast.model_version.isnot(None)
                ).order_by(desc(DLTForecast.create_time))
            results = session.execute(stmt).scalars().all()

            # 按 model_version 去重，保留最新的一条记录（代表该模型的最终质量）
            model_map = {}
            for rec in results:
                model_name = rec.model_version
                if model_name not in model_map:
                    model_map[model_name] = rec
            tasks = []
            for model_name, rec in model_map.items():
                # 从模型文件名解析超参数（如果有）
                # 例如: ssq_epochs200_bs128_seq30_lr0_00005_1234567890.pt
                try:
                    parts = model_name.replace('.pt', '').split('_')
                    epochs = None
                    batch_size = None
                    seq_len = None
                    learning_rate = None
                    for p in parts:
                        if p.startswith('epochs'):
                            epochs = int(p.replace('epochs', ''))
                        elif p.startswith('bs'):
                            batch_size = int(p.replace('bs', ''))
                        elif p.startswith('seq'):
                            seq_len = int(p.replace('seq', ''))
                        elif p.startswith('lr'):
                            lr_str = p.replace('lr', '').replace('_', '.')
                            try:
                                learning_rate = float(lr_str)
                            except (ValueError, TypeError):
                                logger.debug(f"模型 {model_name} 学习率解析失败: {lr_str!r}")
                except (ValueError, IndexError, AttributeError):
                    logger.debug(f"模型文件名超参解析失败，跳过: {model_name!r}")
                if epochs is None or batch_size is None:
                    continue
                task_info = {
                    'model_name': model_name,
                    'epochs': epochs,
                    'batch_size': batch_size,
                    'seq_len': seq_len,
                    'learning_rate': learning_rate,
                    'quality_score': rec.quality_score,
                    'create_time': rec.create_time,
                }
                tasks.append(task_info)
            return tasks

    @classmethod
    def _build_task_text(cls, task: Dict[str, Any]) -> str:
        text = (
            f"模型: {task['model_name']} "
            f"轮数: {task['epochs']} "
            f"批次: {task['batch_size']} "
            f"序列长度: {task['seq_len']} "
            f"学习率: {task['learning_rate']} "
            f"质量评分: {task['quality_score']}"
        )
        return text

    @classmethod
    def retrieve_similar_tasks(cls, lottery_type: str, query: str, top_k: int = None) -> List[Dict[str, Any]]:
        if top_k is None:
            top_k = settings.RAG_TOP_K
        tasks = cls._fetch_historical_tasks(lottery_type)
        if not tasks:
            return []
        # 仅取最近 200 条参与相似检索，避免历史任务过多时编码过久
        tasks = tasks[:200]
        model = cls._get_embedding_model()
        # 批量编码（比逐条 encode 快一个数量级），一次性算完所有历史任务向量
        texts = [cls._build_task_text(t) for t in tasks]
        task_embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        query_emb = model.encode(query, normalize_embeddings=True)
        sims = np.asarray(task_embs) @ np.asarray(query_emb)
        top_idx = np.argsort(sims)[::-1][:top_k]
        return [tasks[int(i)] for i in top_idx]

    @classmethod
    def _local_default_hyperparams(cls, lottery_type: str, reason: str) -> Dict[str, Any]:
        """大模型不可用时的本地经验超参兜底，保证推荐功能始终可用"""
        return {
            "epochs": 200,
            "batch_size": 128,
            "seq_len": 50,
            "learning_rate": 5e-5,
            "reason": reason,
        }

    @classmethod
    def recommend_hyperparams(cls, lottery_type: str, description: str = "") -> Dict[str, Any]:
        lottery_name = "双色球" if lottery_type == 'ssq' else "大乐透"

        # 未配置大模型 或 已认证熔断：直接本地兜底，跳过嵌入模型加载与大模型调用
        if not _llm_configured() or cls._llm_auth_failed:
            reason = ("大模型认证失败，已切换本地经验推荐" if cls._llm_auth_failed
                      else "未配置大模型，使用本地经验推荐")
            logger.info(reason)
            return cls._local_default_hyperparams(lottery_type, reason)

        # RAG 相似任务检索（默认关闭：需加载嵌入模型约 10s；开启后失败也不阻断主流程）
        similar_info = "无历史相似任务，请根据通用经验推荐。"
        if getattr(settings, "RAG_ENABLED", False):
            try:
                query_text = f"{lottery_type} {description}"
                similar_tasks = cls.retrieve_similar_tasks(lottery_type, query_text)
                if similar_tasks:
                    parts = []
                    for idx, task in enumerate(similar_tasks, 1):
                        parts.append(
                            f"\n--- 相似任务 {idx} ---\n"
                            f"模型: {task['model_name']}\n"
                            f"轮数: {task['epochs']}\n"
                            f"批次: {task['batch_size']}\n"
                            f"序列长度: {task['seq_len']}\n"
                            f"学习率: {task['learning_rate']}\n"
                            f"质量评分: {task['quality_score']}\n"
                        )
                    similar_info = "".join(parts)
            except Exception:
                logger.warning(f"相似任务检索失败，跳过 RAG: {traceback.format_exc()}")

        # 大模型推荐；调用失败/超时/返回异常时回退本地默认，不让前端干等报错
        try:
            client = cls._get_llm_client()
            user_prompt = USER_PROMPT_TEMPLATE.format(
                lottery_type=lottery_type,
                lottery_name=lottery_name,
                similar_tasks=similar_info
            )
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content

            try:
                recommendation = json.loads(content)
            except json.JSONDecodeError:
                import re
                json_match = re.search(r'\{.*\}', content, re.DOTALL)
                if json_match:
                    recommendation = json.loads(json_match.group())
                else:
                    raise ValueError(f"大模型返回非 JSON 格式: {content}")

            required = ["epochs", "batch_size", "seq_len", "learning_rate"]
            for field in required:
                if field not in recommendation:
                    raise ValueError(f"推荐结果缺少字段: {field}")
            recommendation.setdefault("reason", "大模型智能推荐")
            return recommendation
        except Exception as e:
            # 认证类错误(401/403，key 无效) → 熔断，后续请求直接兜底不再等待
            if getattr(e, "status_code", None) in (401, 403) or "Authentication" in type(e).__name__:
                cls._llm_auth_failed = True
                logger.error("大模型认证失败(key 无效)，已熔断并切换本地推荐")
            else:
                logger.error(f"大模型推荐失败，回退本地默认超参: {traceback.format_exc()}")
            return cls._local_default_hyperparams(lottery_type, "大模型暂不可用，已使用本地经验推荐")

    @classmethod
    def recommend_models(cls, lottery_type: str, top_k: int = None) -> List[str]:
        """推荐模型：优先按回测真实命中率（自我学习反馈），无评分时回退到质量评分"""
        top_k = top_k or settings.AGENT_MODEL_TOP_K
        # 自我学习反馈：从 model_score 表取回测命中率最高的模型
        from app.services.backtest_service import get_top_models
        try:
            scored = get_top_models(lottery_type, top_k)
            if scored:
                return scored
        except Exception:
            pass
        # 回退：按预测质量评分排序
        tasks = cls._fetch_historical_tasks(lottery_type)
        if not tasks:
            return []
        # 按质量评分降序排序
        sorted_tasks = sorted(tasks, key=lambda x: x.get('quality_score', 0), reverse=True)
        return [t['model_name'] for t in sorted_tasks[:top_k] if t.get('model_name')]