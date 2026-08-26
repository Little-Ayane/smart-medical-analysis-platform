"""
数据访问层抽象接口
定义统一的数据源访问规范，支持 MySQL / Hive 等多种后端
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class QueryResult:
    """查询结果封装"""
    rows: List[Dict[str, Any]]
    row_count: int
    columns: List[str]
    elapsed_ms: float = 0  # 查询耗时(毫秒)


class BaseDAO(ABC):
    """数据访问对象抽象基类"""

    @abstractmethod
    def connect(self) -> None:
        """建立连接"""
        pass

    @abstractmethod
    def close(self) -> None:
        """关闭连接"""
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """测试连接是否可用"""
        pass

    @abstractmethod
    def execute_query(self, sql: str, params: tuple = None,
                      use_cache: bool = True) -> List[Dict[str, Any]]:
        """
        执行查询SQL，返回结果列表

        Args:
            sql: SQL语句
            params: 参数化查询的参数
            use_cache: 是否使用缓存

        Returns:
            查询结果列表，每行为一个字典
        """
        pass

    @abstractmethod
    def execute_scalar(self, sql: str, params: tuple = None) -> Any:
        """
        执行查询SQL，返回单个标量值

        Args:
            sql: SQL语句
            params: 参数化查询的参数

        Returns:
            单个值
        """
        pass

    @abstractmethod
    def get_table_count(self, table_name: str) -> int:
        """获取表的记录数"""
        pass

    @abstractmethod
    def get_dimension_values(self, table_name: str, column_name: str,
                             distinct: bool = True) -> List[Any]:
        """获取维度表的某列所有值"""
        pass

    def get_dialect(self) -> str:
        """返回SQL方言标识 (mysql / hive)"""
        return "unknown"

    def supports_index(self) -> bool:
        """是否支持索引"""
        return False

    def supports_transaction(self) -> bool:
        """是否支持事务"""
        return False
