"""
SQL方言适配器
处理 MySQL 与 HiveQL 之间的语法差异
"""


class SQLDialect:
    """SQL方言适配器"""

    @staticmethod
    def adapt(sql: str, dialect: str) -> str:
        """
        根据目标方言适配SQL

        Args:
            sql: 原始SQL（MySQL方言）
            dialect: 目标方言 (mysql / hive)

        Returns:
            适配后的SQL
        """
        if dialect == "mysql":
            return sql
        elif dialect == "hive":
            return SQLDialect.mysql_to_hive(sql)
        return sql

    @staticmethod
    def mysql_to_hive(sql: str) -> str:
        """
        将MySQL SQL转为HiveQL

        主要差异：
        1. LIMIT 语法相同
        2. 反引号 -> 不需要（Hive用反引号也行）
        3. GROUP BY 别名问题
        4. 函数差异：IFNULL -> COALESCE, NOW() -> current_timestamp
        5. 字符串连接：CONCAT 相同
        6. 日期函数差异
        """
        result = sql

        # 1. IFNULL -> COALESCE
        result = result.replace("IFNULL(", "COALESCE(")

        # 2. NOW() -> current_timestamp
        result = result.replace("NOW()", "current_timestamp()")

        # 3. CURDATE() -> current_date()
        result = result.replace("CURDATE()", "current_date()")

        # 4. LIMIT offset 语法：MySQL支持 LIMIT n OFFSET m，Hive需用子查询
        #    简单处理：Hive 2.x+ 已支持 LIMIT offset

        # 5. 布尔值
        result = result.replace("= TRUE", "= true")
        result = result.replace("= FALSE", "= false")

        # 6. AUTO_INCREMENT 无关（DDL，不影响查询）

        return result

    @staticmethod
    def get_create_index_sql(table_name: str, column_name: str,
                             dialect: str) -> str:
        """生成建索引SQL（Hive不支持）"""
        if dialect == "hive":
            return ""  # Hive不支持索引
        idx_name = f"idx_{table_name}_{column_name}"
        return f"CREATE INDEX {idx_name} ON {table_name} ({column_name})"

    @staticmethod
    def get_explain_sql(sql: str, dialect: str) -> str:
        """生成执行计划SQL"""
        if dialect == "hive":
            return f"EXPLAIN {sql}"
        return f"EXPLAIN {sql}"
