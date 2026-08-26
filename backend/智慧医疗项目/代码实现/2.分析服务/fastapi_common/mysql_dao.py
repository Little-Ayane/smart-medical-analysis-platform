"""
MySQL数据访问层
负责MySQL数据库连接管理和查询操作
实现 BaseDAO 接口，支持通过 DAOFactory 切换数据源
"""
import time
import pymysql
from pymysql.cursors import DictCursor
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
import sys
import os
import hashlib
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # fastapi_common 目录（平级导入 database/base_dao）

from database import db_config
from base_dao import BaseDAO


import json
from decimal import Decimal

# ------------------------------------------------------------
# 持久化预聚合层（medical_db.api_cache，kind=2）
# 进程内缓存 TTL 只有 300s 且随重启消失，冷查询代价极高（DRG 聚合实测 >900s）。
# 这里把结果落盘 MySQL，跨重启存活。与 Flask 侧 common.py 共用同一张表，
# 用 kind 区分：kind=1 是 Flask 的 path?k=v 键，kind=2 是这里的 SQL 哈希键。
# 数据是静态快照，故不设过期；失效方式是 TRUNCATE api_cache 后重跑预热。
# ------------------------------------------------------------
DURABLE_KIND_FASTAPI = 2


def _json_default(obj):
    """JSON 序列化兜底：Decimal 转 float，其余非原生类型（datetime 等）转 str。"""
    if isinstance(obj, Decimal):
        return float(obj)
    try:
        return str(obj)
    except Exception:
        return None


def _durable_conn():
    """连接缓存表所在库（medical_db）。

    db_config 是 DatabaseConfig dataclass（属性访问，非 dict）。
    """
    return pymysql.connect(
        host=os.getenv("MEDICAL_DB_HOST", db_config.host),
        port=int(os.getenv("MEDICAL_DB_PORT", str(db_config.port))),
        user=os.getenv("MEDICAL_DB_USER", db_config.user),
        password=os.getenv("MEDICAL_DB_PASSWORD", db_config.password),
        database=os.getenv("MEDICAL_DB_DATABASE", "medical_db"),
        charset="utf8mb4",
        cursorclass=DictCursor,
    )


class QueryCache:
    """查询缓存：进程内 TTL + medical_db.api_cache 持久化兜底。"""

    def __init__(self, ttl_seconds=300, max_size=500):
        self.cache = {}
        self.ttl = ttl_seconds
        self.max_size = max_size
        self._durable_ready = False

    def get_key(self, sql, params):
        content = f"{sql}:{params}"
        return hashlib.md5(content.encode()).hexdigest()

    def _durable_get(self, key):
        """读 api_cache；表不存在/库异常一律当未命中，绝不影响请求。"""
        try:
            conn = _durable_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT payload FROM api_cache "
                        "WHERE kind=%s AND cache_key_hash=%s",
                        (DURABLE_KIND_FASTAPI, key))
                    row = cur.fetchone()
            finally:
                conn.close()
            if row:
                return json.loads(row["payload"])
        except Exception:
            pass
        return None

    def _durable_set(self, key, data, sql):
        """写 api_cache（幂等 upsert）；任何异常静默跳过，内存缓存仍有效。"""
        try:
            conn = _durable_conn()
            try:
                with conn.cursor() as cur:
                    if not self._durable_ready:
                        cur.execute("""
                            CREATE TABLE IF NOT EXISTS api_cache (
                              kind           TINYINT UNSIGNED NOT NULL,
                              cache_key_hash CHAR(32) CHARACTER SET ascii
                                             COLLATE ascii_bin NOT NULL,
                              cache_key      TEXT CHARACTER SET utf8mb4
                                             COLLATE utf8mb4_bin NULL,
                              payload        LONGTEXT NOT NULL,
                              updated_at     TIMESTAMP NOT NULL
                                             DEFAULT CURRENT_TIMESTAMP
                                             ON UPDATE CURRENT_TIMESTAMP,
                              PRIMARY KEY (kind, cache_key_hash)
                            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
                        self._durable_ready = True
                    cur.execute(
                        "INSERT INTO api_cache (kind, cache_key_hash, cache_key, payload) "
                        "VALUES (%s, %s, %s, %s) "
                        "ON DUPLICATE KEY UPDATE payload=VALUES(payload), "
                        "cache_key=VALUES(cache_key)",
                        (DURABLE_KIND_FASTAPI, key, sql[:4000],
                         json.dumps(data, ensure_ascii=False, default=_json_default)))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

    def get(self, sql, params):
        key = self.get_key(sql, params)
        if key in self.cache:
            data, timestamp = self.cache[key]
            if datetime.now() - timestamp < timedelta(seconds=self.ttl):
                return data
            else:
                del self.cache[key]
        # 持久化兜底（跨重启）：命中后回填内存
        data = self._durable_get(key)
        if data is not None:
            self.cache[key] = (data, datetime.now())
            return data
        return None

    def set(self, sql, params, data):
        key = self.get_key(sql, params)
        # 缓存满时清理最旧的条目
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.cache, key=lambda k: self.cache[k][1])
            del self.cache[oldest_key]
        self.cache[key] = (data, datetime.now())
        self._durable_set(key, data, sql)

    def clear(self):
        self.cache.clear()


class MySQLDAO(BaseDAO):
    """MySQL数据访问对象"""

    def __init__(self):
        self.config = db_config
        self.cache = QueryCache(ttl_seconds=300, max_size=500)
        self._pool = []
        self._pool_size = getattr(self.config, 'pool_size', 10)

    def connect(self):
        """建立连接（由连接池管理）"""
        pass

    def close(self):
        """关闭所有连接"""
        for conn in self._pool:
            try:
                conn.close()
            except Exception:
                pass
        self._pool.clear()

    @contextmanager
    def get_connection(self):
        """获取数据库连接（上下文管理器）"""
        conn = None
        try:
            conn = pymysql.connect(
                host=self.config.host,
                port=self.config.port,
                user=self.config.user,
                password=self.config.password,
                database=self.config.database,
                charset=self.config.charset,
                cursorclass=DictCursor,
                autocommit=True
            )
            yield conn
        except pymysql.MySQLError as e:
            print(f"数据库连接错误: {e}")
            raise
        finally:
            if conn:
                conn.close()

    @contextmanager
    def get_cursor(self, connection=None):
        """获取游标（上下文管理器）"""
        if connection:
            cursor = connection.cursor()
            try:
                yield cursor
            finally:
                cursor.close()
        else:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                try:
                    yield cursor
                finally:
                    cursor.close()

    def execute_query(self, sql: str, params: tuple = None,
                      use_cache: bool = True) -> List[Dict[str, Any]]:
        """执行查询SQL，返回结果列表"""
        if use_cache:
            cached = self.cache.get(sql, params)
            if cached is not None:
                return cached

        start = time.time()
        with self.get_cursor() as cursor:
            cursor.execute(sql, params)
            result = cursor.fetchall()

        elapsed = (time.time() - start) * 1000
        if elapsed > 1000:
            print(f"[慢查询] {elapsed:.0f}ms | {sql[:120]}...")

        if use_cache:
            self.cache.set(sql, params, result)

        return result

    def execute_scalar(self, sql: str, params: tuple = None) -> Any:
        """执行查询SQL，返回单个值"""
        with self.get_cursor() as cursor:
            cursor.execute(sql, params)
            result = cursor.fetchone()
            if result:
                return list(result.values())[0]
            return None

    def execute_update(self, sql: str, params: tuple = None) -> int:
        """执行更新SQL，返回影响行数"""
        with self.get_cursor() as cursor:
            affected_rows = cursor.execute(sql, params)
            return affected_rows

    def execute_many(self, sql: str, params_list: List[tuple]) -> int:
        """批量执行SQL，返回影响行数"""
        with self.get_cursor() as cursor:
            affected_rows = cursor.executemany(sql, params_list)
            return affected_rows

    def get_table_count(self, table_name: str) -> int:
        """获取表的记录数"""
        sql = f"SELECT COUNT(*) as cnt FROM {table_name}"
        return self.execute_scalar(sql)

    def get_dimension_values(self, table_name: str, column_name: str,
                             distinct: bool = True) -> List[Any]:
        """获取维度表的某列所有值"""
        distinct_str = "DISTINCT" if distinct else ""
        sql = f"SELECT {distinct_str} {column_name} FROM {table_name} ORDER BY {column_name}"
        results = self.execute_query(sql)
        return [row[column_name] for row in results]

    def test_connection(self) -> bool:
        """测试数据库连接"""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    result = cursor.fetchone()
                    return result is not None
        except Exception as e:
            print(f"连接测试失败: {e}")
            return False

    def get_dialect(self) -> str:
        return "mysql"

    def supports_index(self) -> bool:
        return True

    def supports_transaction(self) -> bool:
        return True


# 全局DAO实例（兼容旧代码）
mysql_dao = MySQLDAO()
