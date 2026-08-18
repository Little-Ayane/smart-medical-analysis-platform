"""
SQL构建器
负责动态生成SQL查询语句
"""
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class QueryConfig:
    """查询配置"""
    dimensions: List[str] = field(default_factory=list)
    metrics: List[str] = field(default_factory=list)
    filters: Dict[str, Any] = field(default_factory=dict)
    sort: Optional[Dict[str, str]] = None
    limit: Optional[int] = None
    offset: Optional[int] = None


# 维度映射：前端维度名 -> (表名, 列名, 别名)
DIMENSION_MAP = {
    # 医院维度
    "hospital": ("dim_hospital", "hospital_id", "hospital"),
    "hospital_name": ("dim_hospital", "facility_name", "hospital_name"),
    "hospital_area": ("dim_hospital", "hospital_service_area", "hospital_area"),
    "hospital_county": ("dim_hospital", "hospital_county", "hospital_county"),

    # 患者维度
    "age_group": ("dim_patient", "age_group", "age_group"),
    "gender": ("dim_patient", "gender", "gender"),
    "race": ("dim_patient", "race", "race"),
    "ethnicity": ("dim_patient", "ethnicity", "ethnicity"),
    "zip_code": ("dim_patient", "zip_code_3digits", "zip_code"),

    # 诊断维度
    "diagnosis_code": ("dim_diagnosis", "ccsr_diagnosis_code", "diagnosis_code"),
    "diagnosis_desc": ("dim_diagnosis", "ccsr_diagnosis_description", "diagnosis_desc"),

    # 手术维度
    "procedure_code": ("dim_procedure", "ccsr_procedure_code", "procedure_code"),
    "procedure_desc": ("dim_procedure", "ccsr_procedure_description", "procedure_desc"),

    # DRG维度
    "drg_code": ("dim_drg", "apr_drg_code", "drg_code"),
    "drg_desc": ("dim_drg", "apr_drg_description", "drg_desc"),
    "mdc_code": ("dim_drg", "apr_mdc_code", "mdc_code"),
    "mdc_desc": ("dim_drg", "apr_mdc_description", "mdc_desc"),
    "severity_code": ("dim_drg", "apr_severity_code", "severity_code"),
    "severity_desc": ("dim_drg", "apr_severity_description", "severity_desc"),
    "risk_mortality": ("dim_drg", "apr_risk_of_mortality", "risk_mortality"),
    "medical_surgical": ("dim_drg", "apr_medical_surgical", "medical_surgical"),

    # 支付方式维度
    "payment_type": ("dim_payment", "payment_typology_1", "payment_type"),
    "payment_type_2": ("dim_payment", "payment_typology_2", "payment_type_2"),
    "payment_type_3": ("dim_payment", "payment_typology_3", "payment_type_3"),

    # 时间维度
    "year": ("dim_time", "discharge_year", "year"),

    # 事实表维度
    "admission_type": ("fact_discharge", "type_of_admission", "admission_type"),
    "disposition": ("fact_discharge", "patient_disposition", "disposition"),
    "ed_indicator": ("fact_discharge", "emergency_department_indicator", "ed_indicator"),
}

# 指标映射：前端指标名 -> (SQL聚合函数, 列名, 别名)
METRIC_MAP = {
    # 基础计数
    "cases": ("COUNT", "*", "cases"),

    # 费用指标
    "total_charges": ("SUM", "total_charges", "total_charges"),
    "avg_charges": ("AVG", "total_charges", "avg_charges"),
    "median_charges": ("PERCENTILE_CONT", "total_charges", "median_charges"),

    # 成本指标
    "total_costs": ("SUM", "total_costs", "total_costs"),
    "avg_costs": ("AVG", "total_costs", "avg_costs"),

    # 住院天数指标
    "total_stay": ("SUM", "length_of_stay", "total_stay"),
    "avg_stay": ("AVG", "length_of_stay", "avg_stay"),
    "max_stay": ("MAX", "length_of_stay", "max_stay"),
    "min_stay": ("MIN", "length_of_stay", "min_stay"),

    # 计算指标
    "cost_ratio": ("CUSTOM", "total_costs / total_charges", "cost_ratio"),
    "charges_per_day": ("CUSTOM", "total_charges / length_of_stay", "charges_per_day"),
}

# 筛选条件映射
FILTER_MAP = {
    "year": ("dim_time", "discharge_year", "="),
    "year_start": ("dim_time", "discharge_year", ">="),
    "year_end": ("dim_time", "discharge_year", "<="),
    "hospital_area": ("dim_hospital", "hospital_service_area", "="),
    "hospital_county": ("dim_hospital", "hospital_county", "="),
    "hospital_name": ("dim_hospital", "facility_name", "LIKE"),
    "age_group": ("dim_patient", "age_group", "="),
    "gender": ("dim_patient", "gender", "="),
    "race": ("dim_patient", "race", "="),
    "ethnicity": ("dim_patient", "ethnicity", "="),
    "diagnosis_desc": ("dim_diagnosis", "ccsr_diagnosis_description", "LIKE"),
    "procedure_desc": ("dim_procedure", "ccsr_procedure_description", "LIKE"),
    "drg_desc": ("dim_drg", "apr_drg_description", "LIKE"),
    "mdc_desc": ("dim_drg", "apr_mdc_description", "LIKE"),
    "severity_desc": ("dim_drg", "apr_severity_description", "="),
    "risk_mortality": ("dim_drg", "apr_risk_of_mortality", "="),
    "medical_surgical": ("dim_drg", "apr_medical_surgical", "="),
    "payment_type": ("dim_payment", "payment_typology_1", "="),
    "admission_type": ("fact_discharge", "type_of_admission", "="),
}


class SQLBuilder:
    """SQL构建器"""

    def __init__(self):
        self.base_table = "fact_discharge"
        self.joined_tables = set()

    def _reset(self):
        """重置构建器状态"""
        self.joined_tables.clear()

    def _get_join_clause(self, dimension: str) -> Tuple[str, str]:
        """获取JOIN子句"""
        if dimension not in DIMENSION_MAP:
            raise ValueError(f"未知维度: {dimension}")

        table_name, column_name, alias = DIMENSION_MAP[dimension]
        join_alias = table_name.replace("dim_", "d_").replace("fact_", "f_")

        if table_name == self.base_table:
            return "", "f"

        if table_name not in self.joined_tables:
            self.joined_tables.add(table_name)
            # 根据表名确定JOIN条件
            if table_name == "dim_hospital":
                join_condition = f"f.hospital_id = {join_alias}.hospital_id"
            elif table_name == "dim_patient":
                join_condition = f"f.patient_demo_id = {join_alias}.patient_demo_id"
            elif table_name == "dim_diagnosis":
                join_condition = f"f.diagnosis_id = {join_alias}.diagnosis_id"
            elif table_name == "dim_procedure":
                join_condition = f"f.procedure_id = {join_alias}.procedure_id"
            elif table_name == "dim_drg":
                join_condition = f"f.drg_id = {join_alias}.drg_id"
            elif table_name == "dim_payment":
                join_condition = f"f.payment_id = {join_alias}.payment_id"
            elif table_name == "dim_time":
                join_condition = f"f.year_id = {join_alias}.year_id"
            else:
                join_condition = ""

            return f"JOIN {table_name} {join_alias} ON {join_condition}", join_alias

        return "", join_alias

    def _get_column_reference(self, dimension: str) -> str:
        """获取列引用"""
        if dimension not in DIMENSION_MAP:
            raise ValueError(f"未知维度: {dimension}")

        table_name, column_name, alias = DIMENSION_MAP[dimension]

        if table_name == self.base_table:
            return f"f.{column_name}"

        join_alias = table_name.replace("dim_", "d_").replace("fact_", "f_")
        return f"{join_alias}.{column_name}"

    def _get_metric_expression(self, metric: str) -> str:
        """获取指标表达式"""
        if metric not in METRIC_MAP:
            raise ValueError(f"未知指标: {metric}")

        agg_func, column, alias = METRIC_MAP[metric]

        if agg_func == "COUNT":
            return f"COUNT(*) as {alias}"
        elif agg_func == "CUSTOM":
            return f"{column} as {alias}"
        elif agg_func in ("PERCENTILE_CONT", "PERCENTILE_DISC"):
            # MySQL不直接支持PERCENTILE_CONT，使用近似方法
            return f"AVG(f.{column}) as {alias}"
        else:
            return f"{agg_func}(f.{column}) as {alias}"

    def _build_where_clause(self, filters: Dict[str, Any]) -> Tuple[str, List[Any]]:
        """构建WHERE子句"""
        if not filters:
            return "", []

        conditions = []
        params = []

        for key, value in filters.items():
            if key not in FILTER_MAP:
                continue

            table_name, column_name, operator = FILTER_MAP[key]
            join_alias = table_name.replace("dim_", "d_").replace("fact_", "f_")

            if table_name == self.base_table:
                col_ref = f"f.{column_name}"
            else:
                col_ref = f"{join_alias}.{column_name}"

            if operator == "LIKE":
                conditions.append(f"{col_ref} LIKE %s")
                params.append(f"%{value}%")
            elif operator in (">=", "<=", "=", "!=", ">", "<"):
                conditions.append(f"{col_ref} {operator} %s")
                params.append(value)
            else:
                conditions.append(f"{col_ref} = %s")
                params.append(value)

        where_clause = " AND ".join(conditions)
        return where_clause, params

    def build_aggregate_query(self, config: QueryConfig) -> Tuple[str, List[Any]]:
        """
        构建聚合查询SQL

        Args:
            config: 查询配置

        Returns:
            SQL语句和参数
        """
        self._reset()
        self.joined_tables.add(self.base_table)

        # 构建SELECT子句
        select_parts = []
        for dim in config.dimensions:
            col_ref = self._get_column_reference(dim)
            _, _, alias = DIMENSION_MAP[dim]
            select_parts.append(f"{col_ref} as {alias}")

        for metric in config.metrics:
            select_parts.append(self._get_metric_expression(metric))

        select_clause = ", ".join(select_parts)

        # 构建JOIN子句
        join_parts = []
        # JOIN维度表
        for dim in config.dimensions:
            join_clause, _ = self._get_join_clause(dim)
            if join_clause:
                join_parts.append(join_clause)

        # JOIN筛选条件中使用的表
        for key in config.filters.keys():
            if key in FILTER_MAP:
                table_name, _, _ = FILTER_MAP[key]
                if table_name != self.base_table:
                    # 创建一个虚拟的维度名来触发JOIN
                    for dim_name, (tbl, _, _) in DIMENSION_MAP.items():
                        if tbl == table_name:
                            join_clause, _ = self._get_join_clause(dim_name)
                            if join_clause:
                                join_parts.append(join_clause)
                            break

        # 构建WHERE子句
        where_clause, params = self._build_where_clause(config.filters)
        where_sql = f"WHERE {where_clause}" if where_clause else ""

        # 构建GROUP BY子句
        group_parts = []
        for dim in config.dimensions:
            col_ref = self._get_column_reference(dim)
            group_parts.append(col_ref)
        group_clause = "GROUP BY " + ", ".join(group_parts) if group_parts else ""

        # 构建ORDER BY子句
        order_clause = ""
        if config.sort:
            field = config.sort.get("field", config.metrics[0] if config.metrics else "cases")
            order = config.sort.get("order", "desc").upper()
            if field in [m for m in config.metrics]:
                order_clause = f"ORDER BY {field} {order}"

        # 构建LIMIT子句
        limit_clause = ""
        if config.limit:
            limit_clause = f"LIMIT {config.limit}"
            if config.offset:
                limit_clause += f" OFFSET {config.offset}"

        # 组装SQL
        sql = f"""
        SELECT {select_clause}
        FROM {self.base_table} f
        {' '.join(join_parts)}
        {where_sql}
        {group_clause}
        {order_clause}
        {limit_clause}
        """.strip()

        return sql, params

    def build_distribution_query(self, dimension: str, metric: str = "cases",
                                 filters: Dict[str, Any] = None) -> Tuple[str, List[Any]]:
        """
        构建分布查询SQL

        Args:
            dimension: 分布维度
            metric: 统计指标
            filters: 筛选条件

        Returns:
            SQL语句和参数
        """
        config = QueryConfig(
            dimensions=[dimension],
            metrics=[metric],
            filters=filters or {},
            sort={"field": metric, "order": "desc"}
        )
        return self.build_aggregate_query(config)

    def build_drill_down_query(self, current_level: str, current_value: Any,
                               drill_to: str, metrics: List[str],
                               filters: Dict[str, Any] = None) -> Tuple[str, List[Any]]:
        """
        构建下钻查询SQL

        Args:
            current_level: 当前层级
            current_value: 当前值
            drill_to: 下钻目标层级
            metrics: 指标列表
            filters: 筛选条件

        Returns:
            SQL语句和参数
        """
        # 添加当前层级作为筛选条件
        drill_filters = filters.copy() if filters else {}
        drill_filters[current_level] = current_value

        config = QueryConfig(
            dimensions=[drill_to],
            metrics=metrics,
            filters=drill_filters,
            sort={"field": metrics[0] if metrics else "cases", "order": "desc"}
        )
        return self.build_aggregate_query(config)

    def build_time_rollup_query(self, time_level: str, metrics: List[str],
                                filters: Dict[str, Any] = None) -> Tuple[str, List[Any]]:
        """
        构建时间上卷查询SQL

        Args:
            time_level: 时间层级 (year, quarter, month)
            metrics: 指标列表
            filters: 筛选条件

        Returns:
            SQL语句和参数
        """
        config = QueryConfig(
            dimensions=["year"],
            metrics=metrics,
            filters=filters or {},
            sort={"field": "year", "order": "asc"}
        )
        return self.build_aggregate_query(config)

    def build_pivot_query(self, row_dimension: str, col_dimension: str,
                          metric: str, filters: Dict[str, Any] = None) -> Tuple[str, List[Any]]:
        """
        构建透视查询SQL

        Args:
            row_dimension: 行维度
            col_dimension: 列维度
            metric: 指标
            filters: 筛选条件

        Returns:
            SQL语句和参数
        """
        config = QueryConfig(
            dimensions=[row_dimension, col_dimension],
            metrics=[metric],
            filters=filters or {}
        )
        return self.build_aggregate_query(config)

    def build_summary_query(self, metrics: List[str],
                            filters: Dict[str, Any] = None) -> Tuple[str, List[Any]]:
        """
        构建汇总查询SQL（无维度分组）

        Args:
            metrics: 指标列表
            filters: 筛选条件

        Returns:
            SQL语句和参数
        """
        self._reset()
        self.joined_tables.add(self.base_table)

        # 构建SELECT子句
        select_parts = []
        for metric in metrics:
            select_parts.append(self._get_metric_expression(metric))

        select_clause = ", ".join(select_parts)

        # 构建JOIN子句（筛选条件中使用的表）
        join_parts = []
        for key in (filters or {}).keys():
            if key in FILTER_MAP:
                table_name, _, _ = FILTER_MAP[key]
                if table_name != self.base_table:
                    # 创建一个虚拟的维度名来触发JOIN
                    for dim_name, (tbl, _, _) in DIMENSION_MAP.items():
                        if tbl == table_name:
                            join_clause, _ = self._get_join_clause(dim_name)
                            if join_clause:
                                join_parts.append(join_clause)
                            break

        # 构建WHERE子句
        where_clause, params = self._build_where_clause(filters or {})
        where_sql = f"WHERE {where_clause}" if where_clause else ""

        # 组装SQL
        sql = f"""
        SELECT {select_clause}
        FROM {self.base_table} f
        {' '.join(join_parts)}
        {where_sql}
        """.strip()

        return sql, params

    def validate_dimensions(self, dimensions: List[str]) -> List[str]:
        """验证维度列表，返回无效维度"""
        invalid_dims = []
        for dim in dimensions:
            if dim not in DIMENSION_MAP:
                invalid_dims.append(dim)
        return invalid_dims

    def validate_metrics(self, metrics: List[str]) -> List[str]:
        """验证指标列表，返回无效指标"""
        invalid_metrics = []
        for metric in metrics:
            if metric not in METRIC_MAP:
                invalid_metrics.append(metric)
        return invalid_metrics

    def get_available_dimensions(self) -> List[str]:
        """获取所有可用维度"""
        return list(DIMENSION_MAP.keys())

    def get_available_metrics(self) -> List[str]:
        """获取所有可用指标"""
        return list(METRIC_MAP.keys())


# 全局SQL构建器实例
sql_builder = SQLBuilder()
