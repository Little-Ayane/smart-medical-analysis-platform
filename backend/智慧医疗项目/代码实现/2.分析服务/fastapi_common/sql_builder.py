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

# 反规范化列映射：维度名 -> fact_discharge 上的反规范化列。
# 这 11 个维度已回填到事实表（见 database/backfill_denorm.sql），查询时直接引用事实表列
# 以消除对维度表的 JOIN（慢接口优化）。metadata 仍从 DIMENSION_MAP 的维度表取 distinct 值，
# 因此 DIMENSION_MAP 保持指向维度表不变。
DENORM_COLUMN_MAP = {
    # 患者维度（dim_patient）
    "age_group": "age_group",
    "gender": "gender",
    "race": "race",
    # 时间维度（dim_time）
    "year": "discharge_year",
    # DRG 维度（dim_drg）
    "severity_code": "apr_severity_code",
    "severity_desc": "apr_severity_desc",
    "risk_mortality": "apr_risk_mortality",
    "medical_surgical": "apr_medical_surgical",
    # 支付维度（dim_payment）
    "payment_type": "payment_typology_1",
    "payment_type_2": "payment_typology_2",
    "payment_type_3": "payment_typology_3",
    # 医院维度（dim_hospital）
    "hospital_name": "facility_name",
    "hospital_area": "hospital_service_area",
    "hospital_county": "hospital_county",
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

# 维度表 -> 事实表外键列（维度表主键同名）。
# 用于「先按外键聚合、后 JOIN 维度表取名」的两级查询，见 build_aggregate_query。
DIM_TABLE_FK = {
    "dim_hospital": "hospital_id",
    "dim_patient": "patient_demo_id",
    "dim_diagnosis": "diagnosis_id",
    "dim_procedure": "procedure_id",
    "dim_drg": "drg_id",
    "dim_payment": "payment_id",
    "dim_time": "year_id",
}

# 让优化器能走 idx_year_* 覆盖索引族的「全集」谓词。
# fact_discharge 上所有 idx_year_* 索引都以 discharge_year 打头，查询不带年份条件时
# 优化器无法使用它们，聚合会退化成千万次主键回表（实测单条 >900s）。
# discharge_year 无 NULL，故 IS NOT NULL 语义上是全集，但能让优化器做索引范围扫描。
YEAR_SCAN_PREDICATE = "f.discharge_year IS NOT NULL"

# 两级聚合时各指标的拆解方式：
#   inner —— 内层（按事实表外键 GROUP BY）需要产出的列，全部是可再汇总的 SUM/COUNT/MAX/MIN
#   outer —— 外层（按维度表列再聚合）如何由内层结果还原该指标
# 关键：均值必须用 SUM(x)/SUM(cases) 加权重算，AVG(AVG(...)) 会算错。
TWO_LEVEL_METRICS = {
    "cases":          ({"cases": "COUNT(*)"},
                       "SUM(t.cases)"),
    "total_charges":  ({"total_charges": "SUM(f.total_charges)"},
                       "SUM(t.total_charges)"),
    "total_costs":    ({"total_costs": "SUM(f.total_costs)"},
                       "SUM(t.total_costs)"),
    "total_stay":     ({"total_stay": "SUM(f.length_of_stay)"},
                       "SUM(t.total_stay)"),
    "avg_charges":    ({"_sum_charges": "SUM(f.total_charges)", "_cnt": "COUNT(*)"},
                       "SUM(t._sum_charges) / NULLIF(SUM(t._cnt), 0)"),
    "median_charges": ({"_sum_charges": "SUM(f.total_charges)", "_cnt": "COUNT(*)"},
                       "SUM(t._sum_charges) / NULLIF(SUM(t._cnt), 0)"),
    "avg_costs":      ({"_sum_costs": "SUM(f.total_costs)", "_cnt": "COUNT(*)"},
                       "SUM(t._sum_costs) / NULLIF(SUM(t._cnt), 0)"),
    "avg_stay":       ({"_sum_stay": "SUM(f.length_of_stay)", "_cnt": "COUNT(*)"},
                       "SUM(t._sum_stay) / NULLIF(SUM(t._cnt), 0)"),
    "max_stay":       ({"max_stay": "MAX(f.length_of_stay)"},
                       "MAX(t.max_stay)"),
    "min_stay":       ({"min_stay": "MIN(f.length_of_stay)"},
                       "MIN(t.min_stay)"),
    "cost_ratio":     ({"_sum_costs": "SUM(f.total_costs)",
                        "_sum_charges": "SUM(f.total_charges)"},
                       "SUM(t._sum_costs) / NULLIF(SUM(t._sum_charges), 0)"),
    "charges_per_day": ({"_sum_charges": "SUM(f.total_charges)",
                         "_sum_stay": "SUM(f.length_of_stay)"},
                        "SUM(t._sum_charges) / NULLIF(SUM(t._sum_stay), 0)"),
}

# 筛选条件映射
# 已反规范化的维度（year/age_group/gender/race/severity_desc/risk_mortality/
# medical_surgical/payment_type）改为引用 fact_discharge 反规范化列，避免 JOIN 维度表。
FILTER_MAP = {
    "year": ("fact_discharge", "discharge_year", "="),
    "year_start": ("fact_discharge", "discharge_year", ">="),
    "year_end": ("fact_discharge", "discharge_year", "<="),
    "hospital_area": ("fact_discharge", "hospital_service_area", "="),
    "hospital_county": ("fact_discharge", "hospital_county", "="),
    "hospital_name": ("fact_discharge", "facility_name", "LIKE"),
    "age_group": ("fact_discharge", "age_group", "="),
    "gender": ("fact_discharge", "gender", "="),
    "race": ("fact_discharge", "race", "="),
    "ethnicity": ("dim_patient", "ethnicity", "="),
    "diagnosis_desc": ("dim_diagnosis", "ccsr_diagnosis_description", "LIKE"),
    "procedure_desc": ("dim_procedure", "ccsr_procedure_description", "LIKE"),
    "drg_desc": ("dim_drg", "apr_drg_description", "LIKE"),
    "mdc_desc": ("dim_drg", "apr_mdc_description", "LIKE"),
    "severity_desc": ("fact_discharge", "apr_severity_desc", "="),
    "risk_mortality": ("fact_discharge", "apr_risk_mortality", "="),
    "medical_surgical": ("fact_discharge", "apr_medical_surgical", "="),
    "payment_type": ("fact_discharge", "payment_typology_1", "="),
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

        # 反规范化列：直接引用事实表列，无需 JOIN 维度表
        if dimension in DENORM_COLUMN_MAP:
            return "", "f"

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

        # 反规范化列：直接引用事实表列
        if dimension in DENORM_COLUMN_MAP:
            return f"f.{DENORM_COLUMN_MAP[dimension]}"

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
            # 比率型指标必须是「和之比」。原实现直接写 total_costs / total_charges，
            # 在 GROUP BY 查询里是未聚合列，取到的是组内任意一行的值。
            num, den = [c.strip() for c in column.split("/", 1)]
            return f"SUM(f.{num}) / NULLIF(SUM(f.{den}), 0) as {alias}"
        elif agg_func in ("PERCENTILE_CONT", "PERCENTILE_DISC"):
            # MySQL不直接支持PERCENTILE_CONT，使用近似方法
            return f"AVG(f.{column}) as {alias}"
        else:
            return f"{agg_func}(f.{column}) as {alias}"

    def _build_where_clause(self, filters: Dict[str, Any]) -> Tuple[str, List[Any]]:
        """构建WHERE子句（只产出事实表条件，维度表条件转为外键 IN 子查询）"""
        if not filters:
            return "", []

        conditions = []
        params = []

        for key, value in filters.items():
            if key not in FILTER_MAP:
                continue

            table_name, column_name, operator = FILTER_MAP[key]
            op = operator if operator in (">=", "<=", "=", "!=", ">", "<") else "="

            if table_name == self.base_table:
                col_ref = f"f.{column_name}"
                if operator == "LIKE":
                    conditions.append(f"{col_ref} LIKE %s")
                    params.append(f"%{value}%")
                else:
                    conditions.append(f"{col_ref} {op} %s")
                    params.append(value)
            else:
                # 维度表条件 → 事实表外键 IN (子查询)。
                # 维度表都很小（≤1 万行），子查询代价可忽略；这样避免在千万行事实表上
                # JOIN，聚合仍能走覆盖索引。
                fk = DIM_TABLE_FK.get(table_name)
                if not fk:
                    continue
                pred = "LIKE %s" if operator == "LIKE" else f"{op} %s"
                conditions.append(
                    f"f.{fk} IN (SELECT {fk} FROM {table_name} WHERE {column_name} {pred})")
                params.append(f"%{value}%" if operator == "LIKE" else value)

        where_clause = " AND ".join(conditions)
        return where_clause, params

    def _build_where_sql(self, filters: Dict[str, Any]) -> Tuple[str, List[Any]]:
        """WHERE 子句 + 全集年份谓词（解锁 idx_year_* 覆盖索引族）"""
        where_clause, params = self._build_where_clause(filters)
        conditions = [where_clause] if where_clause else []
        # 已有年份条件时不再追加，避免与 year/year_start/year_end 重复
        if not any(k in ("year", "year_start", "year_end") for k in (filters or {})):
            conditions.append(YEAR_SCAN_PREDICATE)
        return ("WHERE " + " AND ".join(conditions)) if conditions else "", params

    @staticmethod
    def _order_limit(config: QueryConfig) -> str:
        """ORDER BY + LIMIT（字段必须是已选指标别名，防注入）"""
        clause = ""
        if config.sort:
            field = config.sort.get("field", config.metrics[0] if config.metrics else "cases")
            order = "ASC" if str(config.sort.get("order", "desc")).lower() == "asc" else "DESC"
            if field in config.metrics:
                clause = f"ORDER BY {field} {order}"
        if config.limit:
            clause += f" LIMIT {int(config.limit)}"
            if config.offset:
                clause += f" OFFSET {int(config.offset)}"
        return clause

    def build_aggregate_query(self, config: QueryConfig) -> Tuple[str, List[Any]]:
        """
        构建聚合查询SQL

        维度全部落在事实表（反规范化列）时走单层聚合；只要有维度需要维度表取名，
        就走两级聚合：先按事实表外键 GROUP BY（可走覆盖索引），再 JOIN 小维度表并
        按维度列重新汇总。这是本项目 common.py 里写明的约定，实测 DRG 聚合
        >900s → 7s。

        Args:
            config: 查询配置

        Returns:
            SQL语句和参数
        """
        self._reset()
        self.joined_tables.add(self.base_table)

        where_sql, params = self._build_where_sql(config.filters)

        # 维度分类：需要 JOIN 维度表的 vs 事实表自带的
        dim_dims, fact_dims = [], []
        for dim in config.dimensions:
            table_name, _, _ = DIMENSION_MAP[dim]
            if dim in DENORM_COLUMN_MAP or table_name == self.base_table:
                fact_dims.append(dim)
            else:
                dim_dims.append(dim)

        if not dim_dims:
            return self._build_single_level(config, where_sql, params)
        return self._build_two_level(config, dim_dims, fact_dims, where_sql, params)

    def _build_single_level(self, config: QueryConfig, where_sql: str,
                            params: List[Any]) -> Tuple[str, List[Any]]:
        """所有维度都在事实表上，单层 GROUP BY 即可。"""
        select_parts = []
        group_parts = []
        for dim in config.dimensions:
            col_ref = self._get_column_reference(dim)
            _, _, alias = DIMENSION_MAP[dim]
            select_parts.append(f"{col_ref} as {alias}")
            group_parts.append(col_ref)

        for metric in config.metrics:
            select_parts.append(self._get_metric_expression(metric))

        group_clause = "GROUP BY " + ", ".join(group_parts) if group_parts else ""

        sql = f"""
        SELECT {', '.join(select_parts)}
        FROM {self.base_table} f
        {where_sql}
        {group_clause}
        {self._order_limit(config)}
        """.strip()
        return sql, params

    def _build_two_level(self, config: QueryConfig, dim_dims: List[str],
                         fact_dims: List[str], where_sql: str,
                         params: List[Any]) -> Tuple[str, List[Any]]:
        """两级聚合：内层按外键预聚合走覆盖索引，外层 JOIN 维度表后重新汇总。

        注意维度表可能是退化维度（dim_drg 有 5761 行但只有 336 个 apr_drg_code），
        因此外层必须按真正的维度列再 GROUP BY 一次，且均值要按
        SUM(x)/SUM(cases) 加权重算 —— AVG(AVG(...)) 会算错。
        """
        # 内层需要携带的外键（同一张维度表只带一次）
        fks = []
        for dim in dim_dims:
            table_name, _, _ = DIMENSION_MAP[dim]
            fk = DIM_TABLE_FK[table_name]
            if fk not in fks:
                fks.append(fk)

        # 内层指标列（按别名去重，多个指标可共用 _cnt/_sum_charges 等）
        inner_metrics: Dict[str, str] = {}
        outer_parts: List[str] = []
        for metric in config.metrics:
            if metric not in METRIC_MAP:
                raise ValueError(f"未知指标: {metric}")
            spec = TWO_LEVEL_METRICS.get(metric)
            if spec is None:
                raise ValueError(f"指标 {metric} 不支持两级聚合")
            inner_exprs, outer_expr = spec
            inner_metrics.update(inner_exprs)
            outer_parts.append(f"{outer_expr} as {METRIC_MAP[metric][2]}")

        # 内层：外键 + 事实表维度列 + 可再汇总的聚合
        inner_select, inner_group = [], []
        for fk in fks:
            inner_select.append(f"f.{fk}")
            inner_group.append(f"f.{fk}")
        for dim in fact_dims:
            col_ref = self._get_column_reference(dim)
            _, _, alias = DIMENSION_MAP[dim]
            inner_select.append(f"{col_ref} as {alias}")
            inner_group.append(col_ref)
        for alias, expr in inner_metrics.items():
            inner_select.append(f"{expr} as {alias}")

        inner_sql = f"""SELECT {', '.join(inner_select)}
            FROM {self.base_table} f
            {where_sql}
            GROUP BY {', '.join(inner_group)}"""

        # 外层：JOIN 维度表取名，再按维度列汇总
        joins, outer_select, outer_group = [], [], []
        joined = set()
        for dim in dim_dims:
            table_name, column_name, alias = DIMENSION_MAP[dim]
            fk = DIM_TABLE_FK[table_name]
            join_alias = table_name.replace("dim_", "d_")
            if table_name not in joined:
                joined.add(table_name)
                joins.append(
                    f"JOIN {table_name} {join_alias} ON t.{fk} = {join_alias}.{fk}")
            outer_select.append(f"{join_alias}.{column_name} as {alias}")
            outer_group.append(f"{join_alias}.{column_name}")
        for dim in fact_dims:
            _, _, alias = DIMENSION_MAP[dim]
            outer_select.append(f"t.{alias}")
            outer_group.append(f"t.{alias}")
        outer_select.extend(outer_parts)

        sql = f"""
        SELECT {', '.join(outer_select)}
        FROM ({inner_sql}) t
        {' '.join(joins)}
        GROUP BY {', '.join(outer_group)}
        {self._order_limit(config)}
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
