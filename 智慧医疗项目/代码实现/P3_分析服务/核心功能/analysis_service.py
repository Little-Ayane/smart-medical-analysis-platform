"""
分析服务层
负责业务逻辑处理和结果格式化
"""
from typing import List, Dict, Any, Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from mysql_dao import mysql_dao
from sql_builder import sql_builder, QueryConfig, DIMENSION_MAP, METRIC_MAP


class AnalysisService:
    """分析服务类"""

    def __init__(self):
        self.dao = mysql_dao
        self.builder = sql_builder

    def dimension_combine(self, dimensions: List[str], metrics: List[str],
                          filters: Dict[str, Any] = None,
                          sort: Dict[str, str] = None,
                          limit: int = 100) -> Dict[str, Any]:
        """
        维度组合选择

        Args:
            dimensions: 维度列表
            metrics: 指标列表
            filters: 筛选条件
            sort: 排序配置
            limit: 返回条数

        Returns:
            查询结果
        """
        # 验证参数
        invalid_dims = self.builder.validate_dimensions(dimensions)
        if invalid_dims:
            raise ValueError(f"无效的维度: {invalid_dims}")

        invalid_metrics = self.builder.validate_metrics(metrics)
        if invalid_metrics:
            raise ValueError(f"无效的指标: {invalid_metrics}")

        # 构建查询配置
        config = QueryConfig(
            dimensions=dimensions,
            metrics=metrics,
            filters=filters or {},
            sort=sort or {"field": metrics[0] if metrics else "cases", "order": "desc"},
            limit=limit
        )

        # 执行查询
        sql, params = self.builder.build_aggregate_query(config)
        results = self.dao.execute_query(sql, tuple(params))

        # 格式化结果
        return {
            "columns": dimensions + metrics,
            "rows": results,
            "total": len(results),
            "sql": sql  # 调试用，生产环境可移除
        }

    def metric_switch(self, dimensions: List[str],
                      metric_groups: Dict[str, List[str]],
                      filters: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        指标切换

        Args:
            dimensions: 维度列表
            metric_groups: 指标组
            filters: 筛选条件

        Returns:
            查询结果
        """
        # 验证参数
        invalid_dims = self.builder.validate_dimensions(dimensions)
        if invalid_dims:
            raise ValueError(f"无效的维度: {invalid_dims}")

        # 收集所有指标
        all_metrics = []
        for group_name, metrics in metric_groups.items():
            for metric in metrics:
                if metric not in all_metrics:
                    all_metrics.append(metric)

        invalid_metrics = self.builder.validate_metrics(all_metrics)
        if invalid_metrics:
            raise ValueError(f"无效的指标: {invalid_metrics}")

        # 构建查询配置
        config = QueryConfig(
            dimensions=dimensions,
            metrics=all_metrics,
            filters=filters or {},
            sort={"field": all_metrics[0] if all_metrics else "cases", "order": "desc"}
        )

        # 执行查询
        sql, params = self.builder.build_aggregate_query(config)
        results = self.dao.execute_query(sql, tuple(params))

        # 按指标组重新组织结果
        formatted_results = []
        for row in results:
            formatted_row = {}
            # 添加维度值
            for dim in dimensions:
                _, _, alias = DIMENSION_MAP[dim]
                formatted_row[alias] = row.get(alias)

            # 按指标组添加指标值
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
        """
        逐级下钻

        Args:
            current_level: 当前层级
            current_value: 当前值
            drill_to: 下钻目标层级
            metrics: 指标列表
            filters: 筛选条件

        Returns:
            下钻结果
        """
        # 验证参数
        if current_level not in DIMENSION_MAP:
            raise ValueError(f"无效的当前层级: {current_level}")
        if drill_to not in DIMENSION_MAP:
            raise ValueError(f"无效的下钻目标层级: {drill_to}")

        invalid_metrics = self.builder.validate_metrics(metrics)
        if invalid_metrics:
            raise ValueError(f"无效的指标: {invalid_metrics}")

        # 构建下钻查询
        drill_filters = filters.copy() if filters else {}
        drill_filters[current_level] = current_value

        sql, params = self.builder.build_drill_down_query(
            current_level, current_value, drill_to, metrics, drill_filters
        )

        results = self.dao.execute_query(sql, tuple(params))

        # 获取面包屑导航
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
        """
        时间上卷

        Args:
            time_level: 时间层级 (year, quarter, month)
            metrics: 指标列表
            filters: 筛选条件
            compare_previous: 是否与上期对比

        Returns:
            时间上卷结果
        """
        # 验证参数
        invalid_metrics = self.builder.validate_metrics(metrics)
        if invalid_metrics:
            raise ValueError(f"无效的指标: {invalid_metrics}")

        # 构建查询
        sql, params = self.builder.build_time_rollup_query(
            time_level, metrics, filters
        )

        results = self.dao.execute_query(sql, tuple(params))

        # 如果需要与上期对比，计算增长率
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
        """
        交叉透视

        Args:
            row_dimension: 行维度
            col_dimension: 列维度
            metric: 指标
            filters: 筛选条件

        Returns:
            透视表结果
        """
        # 验证参数
        if row_dimension not in DIMENSION_MAP:
            raise ValueError(f"无效的行维度: {row_dimension}")
        if col_dimension not in DIMENSION_MAP:
            raise ValueError(f"无效的列维度: {col_dimension}")
        if metric not in METRIC_MAP:
            raise ValueError(f"无效的指标: {metric}")

        # 构建查询
        sql, params = self.builder.build_pivot_query(
            row_dimension, col_dimension, metric, filters
        )

        results = self.dao.execute_query(sql, tuple(params))

        # 转换为透视表格式
        _, _, row_alias = DIMENSION_MAP[row_dimension]
        _, _, col_alias = DIMENSION_MAP[col_dimension]
        _, _, metric_alias = METRIC_MAP[metric]

        # 提取唯一的行和列值
        row_values = sorted(list(set(row.get(row_alias) for row in results)))
        col_values = sorted(list(set(row.get(col_alias) for row in results)))

        # 构建矩阵
        matrix = []
        for row_val in row_values:
            row_data = []
            for col_val in col_values:
                # 查找对应的值
                value = None
                for result in results:
                    if (result.get(row_alias) == row_val and
                            result.get(col_alias) == col_val):
                        value = result.get(metric_alias)
                        break
                row_data.append(value)
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
        """
        汇总统计

        Args:
            metrics: 指标列表
            filters: 筛选条件

        Returns:
            汇总统计结果
        """
        # 验证参数
        invalid_metrics = self.builder.validate_metrics(metrics)
        if invalid_metrics:
            raise ValueError(f"无效的指标: {invalid_metrics}")

        # 构建查询
        sql, params = self.builder.build_summary_query(metrics, filters)

        result = self.dao.execute_query(sql, tuple(params))

        if result:
            return result[0]
        return {}

    def get_metadata(self) -> Dict[str, Any]:
        """
        获取元数据

        Returns:
            维度和指标的元数据
        """
        # 获取维度信息
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

        # 获取指标信息
        metrics = {}
        for metric_name, (func, column, alias) in METRIC_MAP.items():
            metrics[metric_name] = {
                "function": func,
                "column": column,
                "alias": alias
            }

        return {
            "dimensions": dimensions,
            "metrics": metrics
        }

    def _get_breadcrumb(self, current_level: str, current_value: Any) -> List[str]:
        """获取面包屑导航"""
        # 简单实现，可以根据需要扩展
        return [str(current_value)]

    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        db_status = "healthy" if self.dao.test_connection() else "unhealthy"

        return {
            "status": "healthy" if db_status == "healthy" else "degraded",
            "database": db_status,
            "timestamp": self._get_timestamp()
        }

    def _get_timestamp(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime
        return datetime.now().isoformat()


# 全局服务实例
analysis_service = AnalysisService()
