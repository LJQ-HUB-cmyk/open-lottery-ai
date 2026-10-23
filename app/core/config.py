# -*- coding: utf-8 -*-
"""
配置管理模块：从环境变量加载配置信息。
按 APP_ENV 环境变量选择 .env.development / .env.production（默认 development）。
"""
import os
from pathlib import Path

from pydantic import ConfigDict
from pydantic_settings import BaseSettings

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 按运行环境选择配置文件：APP_ENV=production 时读 .env.production，否则 .env.development
_APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
_env_candidate = BASE_DIR / f".env.{_APP_ENV}"
ENV_FILE = _env_candidate if _env_candidate.exists() else BASE_DIR / ".env.development"


class Settings(BaseSettings):
    """
    应用配置类，自动读取当前环境对应的 .env 文件。
    所有字段均从环境变量读取，无硬编码值。
    """
    model_config = ConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # ---------- MySQL 配置 ----------
    MYSQL_HOST: str
    MYSQL_PORT: int
    MYSQL_USER: str
    MYSQL_PASSWORD: str
    MYSQL_DATABASE: str

    @property
    def mysql_url(self) -> str:
        """生成异步 MySQL 连接 URL"""
        return f"mysql+asyncmy://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"

    # ---------- Redis 配置 ----------
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_PASSWORD: str
    REDIS_DB: int

    @property
    def redis_url(self) -> str:
        """生成 Redis 连接 URL"""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ---------- Celery 配置 ----------
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    # ---------- 训练配置 ----------
    MODEL_SAVE_DIR: str
    DEVICE: str

    # ---------- 业务调优参数（均可被 .env 覆盖） ----------
    FETCH_TIMEOUT: int = 120          # 数据抓取脚本子进程超时（秒）
    BACKTEST_PERIODS: int = 30        # 回测滑动窗口期数
    ENSEMBLE_TOP_K: int = 5           # 集成融合取榜单前 K 个模型
    AGENT_MODEL_TOP_K: int = 5        # 智能选模返回前 K 个模型
    MODEL_KEEP_LATEST: int = 80       # 磁盘清理：每个彩种保留最近 N 个模型
    MODEL_KEEP_TOP_SCORED: int = 20   # 磁盘清理：额外保留回测榜单前 N 个模型
    # 休市日期（逗号分隔的 ISO 日期，如国庆/春节休市）；休市期间无开奖，
    # is_draw_day 返回 False，get_target_draw_date 跳到休市后第一个开奖日
    LOTTERY_HOLIDAYS: str = "2026-10-01,2026-10-02,2026-10-03,2026-10-04"

    @property
    def lottery_holidays_set(self) -> set:
        """解析 LOTTERY_HOLIDAYS 为 date 集合"""
        from datetime import date as _date
        result = set()
        for s in self.LOTTERY_HOLIDAYS.split(","):
            s = s.strip()
            if s:
                try:
                    y, m, d = s.split("-")
                    result.add(_date(int(y), int(m), int(d)))
                except (ValueError, AttributeError):
                    pass
        return result

    # ---------- API 配置 ----------
    API_HOST: str
    API_PORT: int

    # ---------- 跨域配置 ----------
    # 逗号分隔的允许来源；生产环境务必显式配置前端域名，不可用 "*"
    CORS_ORIGINS: str = "http://localhost:8888,http://127.0.0.1:8888"

    @property
    def cors_origins_list(self) -> list:
        """解析 CORS_ORIGINS 为去空白的来源列表"""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    # ---------- Celery Worker 并发 ----------
    CELERY_WORKER_CONCURRENCY: int = 4

    # ---------- 自我进化闭环配置 ----------
    SELF_EVOLVE_ENABLED: bool = True     # 是否注册 Celery Beat 定时进化任务
    SELF_EVOLVE_N_MODELS: int = 15       # 每轮进化训练的模型数（建议 10-20）
    SELF_EVOLVE_HOUR: int = 9            # 每日触发小时（本地时区）
    SELF_EVOLVE_MINUTE: int = 30         # 每日触发分钟

    # Agent 相关配置
    DEEPSEEK_API_KEY: str = "your-deepseek-api-key-here"
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com/v1"
    AGENT_ENABLED: bool = True
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"
    RAG_TOP_K: int = 3
    # RAG 向量检索开关：需加载 SentenceTransformer 嵌入模型（首次约 10s）。
    # 默认关闭，智能推荐直接调用大模型/本地兜底；配好有效大模型 key 后可置 true 启用。
    RAG_ENABLED: bool = False


# 创建全局配置实例
settings = Settings()