"""
MySQL数据访问层
负责数据库连接管理和基础查询操作
"""
import pymysql
from pymysql.cursors import DictCursor
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
import sys
import os
import hashlib
import json
from datetime import datetime, timedelta

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from database import db_config


class QueryCache:
    """简单查询缓存"""

    def __init__(self, ttl_seconds=300):  # 默认5分钟缓存
        self.cache = {}
        self.ttl = ttl_seconds

    def get_key(self, sql, params):
        """生成缓存键"""
        content = f"{sql}:{params}"
        return hashlib.md5(content.encode()).hexdigest()

    def get(self, sql, params):
        """获取缓存"""
        key = self.get_key(sql, params)
        if key in self.cache:
            data, timestamp = self.cache[key]
            if datetime.now() - timestamp < timedelta(seconds=self.ttl):
                return data
            else:
                del self.cache[key]
        return None

    def set(self, sql, params, data):
        """设置缓存"""
        key = self.get_key(sql, params)
        self.cache[key] = (data, datetime.now())

    def clear(self):
        """清空缓存"""
        self.cache.clear()


class MySQLDAO:
    """MySQL数据访问对象"""

    def __init__(self):
        self.config = db_config
        self.cache = QueryCache(ttl_seconds=300)  # 5分钟缓存

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

    def execute_query(self, sql: str, params: tuple = None, use_cache: bool = True) -> List[Dict[str, Any]]:
        """执行查询SQL，返回结果列表"""
        # 检查缓存
        if use_cache:
            cached = self.cache.get(sql, params)
            if cached is not None:
                return cached

        # 执行查询
        with self.get_cursor() as cursor:
            cursor.execute(sql, params)
            result = cursor.fetchall()

            # 存入缓存
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

    def table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        sql = """
        SELECT COUNT(*) as cnt
        FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s
        """
        result = self.execute_scalar(sql, (self.config.database, table_name))
        return result > 0

    def get_table_columns(self, table_name: str) -> List[str]:
        """获取表的所有列名"""
        sql = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """
        results = self.execute_query(sql, (self.config.database, table_name))
        return [row['column_name'] for row in results]

    def get_table_count(self, table_name: str) -> int:
        """获取表的记录数"""
        sql = f"SELECT COUNT(*) as cnt FROM {table_name}"
        return self.execute_scalar(sql)

    def get_all_tables(self) -> List[str]:
        """获取数据库中所有表名"""
        sql = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s
        ORDER BY table_name
        """
        results = self.execute_query(sql, (self.config.database,))
        return [row['table_name'] for row in results]

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


# 全局DAO实例
mysql_dao = MySQLDAO()
