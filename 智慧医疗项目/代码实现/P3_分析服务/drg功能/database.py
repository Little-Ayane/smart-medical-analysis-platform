"""
数据库配置
从环境变量读取配置，或使用默认值
"""
import os
from dataclasses import dataclass


@dataclass
class DatabaseConfig:
    """数据库配置"""
    host: str = os.getenv("MYSQL_HOST", "localhost")
    port: int = int(os.getenv("MYSQL_PORT", "3306"))
    user: str = os.getenv("MYSQL_USER", "root")
    password: str = os.getenv("MYSQL_PASSWORD", "")  # 从环境变量读取
    database: str = os.getenv("MYSQL_DATABASE", "medical_db")
    charset: str = "utf8mb4"


@dataclass
class AppConfig:
    """应用配置"""
    host: str = os.getenv("APP_HOST", "0.0.0.0")
    port: int = int(os.getenv("APP_PORT", "8001"))
    debug: bool = os.getenv("APP_DEBUG", "false").lower() == "true"
    workers: int = int(os.getenv("APP_WORKERS", "1"))


# 全局配置实例
db_config = DatabaseConfig()
app_config = AppConfig()
