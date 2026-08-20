"""
Hive数据访问层
负责Hive数据库连接管理和查询操作
通过 Thrift 协议连接 HiveServer2
"""
import time
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from database import hive_config
from base_dao import BaseDAO


class HiveDAO(BaseDAO):
    """Hive数据访问对象"""

    def __init__(self):
        self.config = hive_config
        self._conn = None

    def connect(self):
        """建立Hive连接"""
        try:
            from pyhive import hive
            self._conn = hive.connect(
                host=self.config.host,
                port=self.config.port,
                username=self.config.username,
                database=self.config.database,
                auth=self.config.auth,
                # Kerberos认证（如果需要）
                # kerberos_service_name=self.config.kerberos_service_name,
            )
            return True
        except ImportError:
            print("[HiveDAO] 请安装 pyhive: pip install pyhive[thrift]")
            return False
        except Exception as e:
            print(f"[HiveDAO] 连接失败: {e}")
            return False

    def close(self):
        """关闭连接"""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    @contextmanager
    def get_connection(self):
        """获取Hive连接（上下文管理器）"""
        if self._conn is None:
            self.connect()

        try:
            yield self._conn
        except Exception as e:
            print(f"[HiveDAO] 连接错误: {e}")
            # 尝试重连
            self.close()
            self.connect()
            raise
        finally:
            pass  # Hive连接保持长连接，不在这里关闭

    @contextmanager
    def get_cursor(self):
        """获取游标"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                yield cursor
            finally:
                cursor.close()

    def execute_query(self, sql: str, params: tuple = None,
                      use_cache: bool = True) -> List[Dict[str, Any]]:
        """
        执行HiveQL查询，返回结果列表

        注意：Hive不支持参数化查询（%s），需要字符串拼接
        这里做了方言适配：将MySQL的 %s 占位符转为直接拼接
        """
        # Hive不使用参数化查询，将参数直接拼入SQL
        if params:
            sql = self._apply_params(sql, params)

        start = time.time()
        with self.get_cursor() as cursor:
            cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            rows = cursor.fetchall()

        elapsed = (time.time() - start) * 1000
        if elapsed > 5000:
            print(f"[Hive慢查询] {elapsed:.0f}ms | {sql[:120]}...")

        # 将tuple结果转为dict
        result = []
        for row in rows:
            row_dict = {}
            for i, col in enumerate(columns):
                row_dict[col] = row[i] if i < len(row) else None
            result.append(row_dict)

        return result

    def execute_scalar(self, sql: str, params: tuple = None) -> Any:
        """执行查询，返回单个值"""
        results = self.execute_query(sql, params, use_cache=False)
        if results:
            return list(results[0].values())[0]
        return None

    def get_table_count(self, table_name: str) -> int:
        """获取表的记录数"""
        sql = f"SELECT COUNT(*) AS cnt FROM {table_name}"
        return self.execute_scalar(sql, use_cache=False)

    def get_dimension_values(self, table_name: str, column_name: str,
                             distinct: bool = True) -> List[Any]:
        """获取维度表的某列所有值"""
        distinct_str = "DISTINCT" if distinct else ""
        sql = f"SELECT {distinct_str} {column_name} FROM {table_name} ORDER BY {column_name}"
        results = self.execute_query(sql)
        return [row[column_name] for row in results]

    def test_connection(self) -> bool:
        """测试连接"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                return result is not None
        except Exception as e:
            print(f"[HiveDAO] 连接测试失败: {e}")
            return False

    def get_dialect(self) -> str:
        return "hive"

    def supports_index(self) -> bool:
        return False  # Hive不支持传统索引

    def supports_transaction(self) -> bool:
        return False

    def _apply_params(self, sql: str, params: tuple) -> str:
        """
        将参数化查询转为字符串拼接（Hive不支持 %s 占位符）

        注意：仅用于Hive，MySQL仍使用参数化查询防SQL注入
        """
        result = sql
        for param in params:
            if isinstance(param, str):
                result = result.replace("%s", f"'{param}'", 1)
            elif param is None:
                result = result.replace("%s", "NULL", 1)
            else:
                result = result.replace("%s", str(param), 1)
        return result

    def wait_for_completion(self, timeout: int = 300):
        """
        等待Hive查询完成（Hive异步执行时使用）

        Args:
            timeout: 超时秒数
        """
        pass  # pyhive默认同步执行，无需额外等待


# 全局DAO实例
hive_dao = HiveDAO()
