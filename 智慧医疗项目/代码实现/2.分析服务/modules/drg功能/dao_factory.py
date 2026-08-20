"""
DAO工厂
根据配置自动选择数据源（MySQL / Hive）
"""
from database import app_config
from base_dao import BaseDAO


class DAOFactory:
    """数据源工厂类"""

    _instances = {}

    @classmethod
    def get_dao(cls, source: str = None) -> BaseDAO:
        """
        获取DAO实例

        Args:
            source: 数据源类型 (mysql / hive)，为None时使用配置文件默认值

        Returns:
            BaseDAO 实例
        """
        source = source or app_config.data_source

        if source not in cls._instances:
            if source == "mysql":
                from mysql_dao import MySQLDAO
                cls._instances[source] = MySQLDAO()
            elif source == "hive":
                from hive_dao import HiveDAO
                cls._instances[source] = HiveDAO()
            else:
                raise ValueError(f"不支持的数据源: {source}，可选: mysql / hive")

        return cls._instances[source]

    @classmethod
    def get_available_sources(cls) -> list:
        """获取所有可用的数据源"""
        return ["mysql", "hive"]

    @classmethod
    def clear_cache(cls):
        """清空DAO实例缓存（用于重连）"""
        for dao in cls._instances.values():
            try:
                dao.close()
            except Exception:
                pass
        cls._instances.clear()


# 便捷函数
def get_dao(source: str = None) -> BaseDAO:
    """获取DAO实例的快捷方式"""
    return DAOFactory.get_dao(source)
