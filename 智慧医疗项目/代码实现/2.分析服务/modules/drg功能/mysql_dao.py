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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from database import db_config
from base_dao import BaseDAO


class QueryCache:
    """简单查询缓存（带大小上限）"""

    def __init__(self, ttl_seconds=300, max_size=500):
        self.cache = {}
        self.ttl = ttl_seconds
        self.max_size = max_size

    def get_key(self, sql, params):
        content = f"{sql}:{params}"
        return hashlib.md5(content.encode()).hexdigest()

    def get(self, sql, params):
        key = self.get_key(sql, params)
        if key in self.cache:
            data, timestamp = self.cache[key]
            if datetime.now() - timestamp < timedelta(seconds=self.ttl):
                return data
            else:
                del self.cache[key]
        return None

    def set(self, sql, params, data):
        key = self.get_key(sql, params)
        # 缓存满时清理最旧的条目
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.cache, key=lambda k: self.cache[k][1])
            del self.cache[oldest_key]
        self.cache[key] = (data, datetime.now())

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
