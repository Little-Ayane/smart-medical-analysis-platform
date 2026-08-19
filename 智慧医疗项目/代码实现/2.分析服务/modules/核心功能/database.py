"""
数据库配置
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class DatabaseConfig:
    """数据库配置类"""
    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = "123456"
    database: str = "medical_db"
    charset: str = "utf8mb4"
    pool_size: int = 10
    max_overflow: int = 20
    pool_recycle: int = 3600

    @property
    def connection_string(self) -> str:
        """获取连接字符串"""
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
            f"?charset={self.charset}"
        )

    @property
    def pymysql_connection_string(self) -> str:
        """获取pymysql连接字符串"""
        return (
            f"host={self.host} port={self.port} user={self.user}"
            f" password={self.password} database={self.database}"
            f" charset={self.charset}"
        )


@dataclass
class RedisConfig:
    """Redis配置类"""
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    max_connections: int = 20
    default_timeout: int = 300  # 5分钟缓存


@dataclass
class AppConfig:
    """应用配置类"""
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 4
    log_level: str = "INFO"


# 全局配置实例
db_config = DatabaseConfig()
redis_config = RedisConfig()
app_config = AppConfig()
