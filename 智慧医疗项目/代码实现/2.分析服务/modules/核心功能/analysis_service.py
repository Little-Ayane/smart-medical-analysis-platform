"""
分析服务层
负责业务逻辑处理和结果格式化
支持 MySQL / Hive 多数据源
"""
from typing import List, Dict, Any, Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from dao_factory import get_dao
from sql_builder import sql_builder, QueryConfig, DIMENSION_MAP, METRIC_MAP
from sql_dialect import SQLDialect


class AnalysisService:
    """分析服务类"""

    def __init__(self, data_source: str = None):
        self.dao = get_dao(data_source)
        self.builder = sql_builder
        self.dialect = self.dao.get_dialect()

    def _exec(self, sql: str, params: tuple = None,
              use_cache: bool = True) -> List[Dict[str, Any]]:
        """执行查询（自动适配方言）"""
        sql = SQLDialect.adapt(sql, self.dialect)
        return self.dao.execute_query(sql, params, use_cache)

    def dimension_combine(self, dimensions: List[str], metrics: List[str],
                          filters: Dict[str, Any] = None,
                          sort: Dict[str, str] = None,
                          limit: int = 100) -> Dict[str, Any]:
        """维度组合选择"""
        # 验证参数
        invalid_dims = self.builder.validate_dimensions(dimensions)
        if invalid_dims:
            raise ValueError(f"无效的维度: {invalid_dims}")

        invalid_metrics = self.builder.validate_metrics(metrics)
        if invalid_metrics:
            raise ValueError(f"无效的指标: {invalid_metrics}")

        config = QueryConfig(
            dimensions=dimensions,
            metrics=metrics,
            filters=filters or {},
            sort=sort or {"field": metrics[0] if metrics else "cases", "order": "desc"},
            limit=limit
        )

        sql, params = self.builder.build_aggregate_query(config)
        results = self._exec(sql, tuple(params))

        return {
            "columns": dimensions + metrics,
            "rows": results,
            "total": len(results),
            "sql": sql
        }

    def metric_switch(self, dimensions: List[str],
                      metric_groups: Dict[str, List[str]],
                      filters: Dict[str, Any] = None) -> Dict[str, Any]:
        """指标切换"""
        invalid_dims = self.builder.validate_dimensions(dimensions)
        if invalid_dims:
            raise ValueError(f"无效的维度: {invalid_dims}")

        all_metrics = []
        for group_name, metrics in metric_groups.items():
            for metric in metrics:
                if metric not in all_metrics:
                    all_metrics.append(metric)

        invalid_metrics = self.builder.validate_metrics(all_metrics)
        if invalid_metrics:
            raise ValueError(f"无效的指标: {invalid_metrics}")

        config = QueryConfig(
            dimensions=dimensions,
            metrics=all_metrics,
            filters=filters or {},
            sort={"field": all_metrics[0] if all_metrics else "cases", "order": "desc"}
        )

        sql, params = self.builder.build_aggregate_query(config)
        results = self._exec(sql, tuple(params))

        # 按指标组重新组织结果
        formatted_results = []
        for row in results:
            formatted_row = {}
            for dim in dimensions:
                _, _, alias = DIMENSION_MAP[dim]
                formatted_row[alias] = row.get(alias)

            for group_name, metrics in metric_groups.items():
                formatted_row[group_name] = {}
                for metric in metrics:
                    _, _, alias = METRIC_MAP[metric]
                    formatted_row[group_name][alias] = row.get(alias)

            formatted_results.append(formatted_row)

        return {
            "columns": list(metric_groups.keys()),
            "rows": formatted_results,
            "total": len(formatted_results)
        }

    def drill_down(self, current_level: str, current_value: Any,
                   drill_to: str, metrics: List[str],
                   filters: Dict[str, Any] = None) -> Dict[str, Any]:
        """逐级下钻"""
        if current_level not in DIMENSION_MAP:
            raise ValueError(f"无效的当前层级: {current_level}")
        if drill_to not in DIMENSION_MAP:
            raise ValueError(f"无效的下钻目标层级: {drill_to}")

        invalid_metrics = self.builder.validate_metrics(metrics)
        if invalid_metrics:
            raise ValueError(f"无效的指标: {invalid_metrics}")

        drill_filters = filters.copy() if filters else {}
        drill_filters[current_level] = current_value

        sql, params = self.builder.build_drill_down_query(
            current_level, current_value, drill_to, metrics, drill_filters
        )

        results = self._exec(sql, tuple(params))
        breadcrumb = self._get_breadcrumb(current_level, current_value)

        return {
            "breadcrumb": breadcrumb,
            "current_level": current_level,
            "current_value": current_value,
            "drill_to": drill_to,
            "columns": [drill_to] + metrics,
            "rows": results,
            "total": len(results)
        }

    def time_rollup(self, time_level: str, metrics: List[str],
                    filters: Dict[str, Any] = None,
                    compare_previous: bool = False) -> Dict[str, Any]:
        """时间上卷"""
        invalid_metrics = self.builder.validate_metrics(metrics)
        if invalid_metrics:
            raise ValueError(f"无效的指标: {invalid_metrics}")

        sql, params = self.builder.build_time_rollup_query(time_level, metrics, filters)
        results = self._exec(sql, tuple(params))

        if compare_previous and len(results) > 1:
            for i in range(1, len(results)):
                for metric in metrics:
                    _, _, alias = METRIC_MAP[metric]
                    current_value = results[i].get(alias, 0)
                    previous_value = results[i-1].get(alias, 0)
                    if previous_value and previous_value != 0:
                        growth_rate = ((current_value - previous_value) / previous_value) * 100
                        results[i][f"{alias}_growth_rate"] = round(growth_rate, 2)
                    else:
                        results[i][f"{alias}_growth_rate"] = None

        return {
            "time_level": time_level,
            "columns": ["year"] + metrics,
            "rows": results,
            "total": len(results)
        }

    def pivot(self, row_dimension: str, col_dimension: str,
              metric: str, filters: Dict[str, Any] = None) -> Dict[str, Any]:
        """交叉透视"""
        if row_dimension not in DIMENSION_MAP:
            raise ValueError(f"无效的行维度: {row_dimension}")
        if col_dimension not in DIMENSION_MAP:
            raise ValueError(f"无效的列维度: {col_dimension}")
        if metric not in METRIC_MAP:
            raise ValueError(f"无效的指标: {metric}")

        sql, params = self.builder.build_pivot_query(
            row_dimension, col_dimension, metric, filters
        )
        results = self._exec(sql, tuple(params))

        _, _, row_alias = DIMENSION_MAP[row_dimension]
        _, _, col_alias = DIMENSION_MAP[col_dimension]
        _, _, metric_alias = METRIC_MAP[metric]

        row_values = sorted(list(set(row.get(row_alias) for row in results)))
        col_values = sorted(list(set(row.get(col_alias) for row in results)))

        # 用dict索引替代O(n²)循环
        lookup = {}
        for r in results:
            key = (r.get(row_alias), r.get(col_alias))
            lookup[key] = r.get(metric_alias)

        matrix = []
        for row_val in row_values:
            row_data = [lookup.get((row_val, col_val)) for col_val in col_values]
            matrix.append(row_data)

        return {
            "rows": row_values,
            "columns": col_values,
            "matrix": matrix,
            "row_dimension": row_dimension,
            "col_dimension": col_dimension,
            "metric": metric
        }

    def summary(self, metrics: List[str],
                filters: Dict[str, Any] = None) -> Dict[str, Any]:
        """汇总统计"""
        invalid_metrics = self.builder.validate_metrics(metrics)
        if invalid_metrics:
            raise ValueError(f"无效的指标: {invalid_metrics}")

        sql, params = self.builder.build_summary_query(metrics, filters)
        result = self._exec(sql, tuple(params))

        if result:
            return result[0]
        return {}

    def get_metadata(self) -> Dict[str, Any]:
        """获取元数据"""
        dimensions = {}
        for dim_name, (table, column, alias) in DIMENSION_MAP.items():
            try:
                values = self.dao.get_dimension_values(table, column, distinct=True)
                dimensions[dim_name] = {
                    "table": table,
                    "column": column,
                    "alias": alias,
                    "sample_values": values[:10] if len(values) > 10 else values,
                    "count": len(values)
                }
            except Exception:
                dimensions[dim_name] = {
                    "table": table,
                    "column": column,
                    "alias": alias,
                    "sample_values": [],
                    "count": 0
                }

        metrics = {}
        for metric_name, (func, column, alias) in METRIC_MAP.items():
            metrics[metric_name] = {
                "function": func,
                "column": column,
                "alias": alias
            }

        return {"dimensions": dimensions, "metrics": metrics}

    def _get_breadcrumb(self, current_level: str, current_value: Any) -> List[str]:
        """获取面包屑导航"""
        return [str(current_value)]

    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        db_status = "healthy" if self.dao.test_connection() else "unhealthy"
        return {
            "status": "healthy" if db_status == "healthy" else "degraded",
            "database": db_status,
            "datasource": self.dialect,
            "timestamp": self._get_timestamp()
        }

    def _get_timestamp(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()


# 全局服务实例（默认MySQL）
analysis_service = AnalysisService()
