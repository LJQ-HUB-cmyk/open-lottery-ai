# -*- coding: utf-8 -*-
"""
配置管理模块：从环境变量加载配置信息。
"""
from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from pathlib import Path

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    """
    应用配置类，自动读取 .env.development 或 .env.production。
    """
    model_config = ConfigDict(
        env_file=BASE_DIR / ".env.development",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # ----- MySQL 配置 -----
    MYSQL_HOST: str = "192.168.2.10"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = "123456"
    MYSQL_DATABASE: str = "open-lottery"

    @property
    def mysql_url(self) -> str:
        """生成异步 MySQL 连接 URL"""
        return f"mysql+asyncmy://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"

    # ----- Redis 配置 -----
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    @property
    def redis_url(self) -> str:
        """生成 Redis 连接 URL"""
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    # ----- Celery Broker -----
    CELERY_BROKER_URL: str = "amqp://guest:guest@localhost:5672//"
    CELERY_RESULT_BACKEND: str = "rpc://"

    # ----- 训练存储配置 -----
    MODEL_SAVE_DIR: str = "./models_storage"
    DEVICE: str = "cpu"          # 或 "cuda"

settings = Settings()