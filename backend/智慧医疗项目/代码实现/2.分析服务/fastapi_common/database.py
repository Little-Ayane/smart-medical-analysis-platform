"""
数据库配置
敏感信息从环境变量读取，本地开发可创建 .env 文件
"""
import os
from dataclasses import dataclass, field
from typing import Optional


def _env(key: str, default: str = "") -> str:
    """读取环境变量，支持 .env 文件"""
    return os.environ.get(key, default)


@dataclass
class DatabaseConfig:
    """数据库配置类"""
    host: str = field(default_factory=lambda: _env("MYSQL_HOST", "localhost"))
    port: int = field(default_factory=lambda: int(_env("MYSQL_PORT", "3306")))
    user: str = field(default_factory=lambda: _env("MYSQL_USER", "root"))
    password: str = field(default_factory=lambda: _env("MYSQL_PASSWORD", ""))
    database: str = field(default_factory=lambda: _env("MYSQL_DATABASE", "medical_db"))
    charset: str = "utf8mb4"
    pool_size: int = 10
    max_overflow: int = 20
    pool_recycle: int = 3600

    @property
    def connection_string(self) -> str:
        return (
            f"mysql+pymysql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
            f"?charset={self.charset}"
        )

    @property
    def pymysql_connection_string(self) -> str:
        return (
            f"host={self.host} port={self.port} user={self.user}"
            f" password={self.password} database={self.database}"
            f" charset={self.charset}"
        )


@dataclass
class HiveConfig:
    """Hive配置类"""
    host: str = field(default_factory=lambda: _env("HIVE_HOST", "localhost"))
    port: int = field(default_factory=lambda: int(_env("HIVE_PORT", "10000")))
    username: str = field(default_factory=lambda: _env("HIVE_USER", "root"))
    database: str = field(default_factory=lambda: _env("HIVE_DATABASE", "default"))
    auth: str = field(default_factory=lambda: _env("HIVE_AUTH", "NONE"))
    kerberos_service_name: str = "hive"
    engine: str = "mr"
    queue: str = "default"

    @property
    def connection_string(self) -> str:
        return (
            f"hive://{self.username}@{self.host}:{self.port}"
            f"/{self.database}?auth={self.auth}"
        )


@dataclass
class RedisConfig:
    """Redis配置类"""
    host: str = field(default_factory=lambda: _env("REDIS_HOST", "localhost"))
    port: int = field(default_factory=lambda: int(_env("REDIS_PORT", "6379")))
    db: int = 0
    password: Optional[str] = field(default_factory=lambda: _env("REDIS_PASSWORD") or None)
    max_connections: int = 20
    default_timeout: int = 300


@dataclass
class AppConfig:
    """应用配置类"""
    debug: bool = field(default_factory=lambda: _env("APP_DEBUG", "true").lower() == "true")
    host: str = "0.0.0.0"
    port: int = field(default_factory=lambda: int(_env("APP_PORT", "8000")))
    workers: int = 4
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    data_source: str = field(default_factory=lambda: _env("DATA_SOURCE", "mysql"))


# 全局配置实例
db_config = DatabaseConfig()
hive_config = HiveConfig()
redis_config = RedisConfig()
app_config = AppConfig()
