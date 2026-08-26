"""
DRG分析服务层
负责DRG相关的分析功能：费用排名、住院天数对比、死亡风险对比、CMI排名、离群识别
支持 MySQL / Hive 多数据源
"""
from typing import List, Dict, Any, Optional
import sys
import os
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from dao_factory import get_dao
from sql_builder import sql_builder, QueryConfig, DIMENSION_MAP, METRIC_MAP
from sql_dialect import SQLDialect


def _decimal_to_float(obj):
    """递归把 Decimal 转 float，其余原样返回。"""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _decimal_to_float(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_decimal_to_float(v) for v in obj]
    return obj


class DRGService:
    """DRG分析服务类"""

    def __init__(self, data_source: str = None):
        self.dao = get_dao(data_source)
        self.builder = sql_builder
        self.dialect = self.dao.get_dialect()

    def _exec(self, sql: str, params: tuple = None,
              use_cache: bool = True) -> List[Dict[str, Any]]:
        """执行查询（自动适配方言），并把 Decimal 归一为 float。

        FastAPI 默认 JSON 编码器会把 Decimal 序列化成字符串（"707471"），
        前端 HospitalView 对 total_charges 调 .toLocaleString() 会因此崩。
        这里统一转 float，冷查询与缓存命中结果一致。
        """
        sql = SQLDialect.adapt(sql, self.dialect)
        rows = self.dao.execute_query(sql, params, use_cache)
        return [_decimal_to_float(r) for r in rows]

    def drg_cost_ranking(self, metrics: List[str] = None,
                         filters: Dict[str, Any] = None,
                         limit: int = 20,
                         sort_order: str = "desc") -> Dict[str, Any]:
        """DRG费用排名"""
        if not metrics:
            metrics = ["cases", "total_charges", "avg_charges"]

        invalid_metrics = self.builder.validate_metrics(metrics)
        if invalid_metrics:
            raise ValueError(f"无效的指标: {invalid_metrics}")

        config = QueryConfig(
            dimensions=["drg_code", "drg_desc", "mdc_code", "mdc_desc"],
            metrics=metrics,
            filters=filters or {},
            sort={"field": metrics[0] if metrics else "cases", "order": sort_order},
            limit=limit
        )

        sql, params = self.builder.build_aggregate_query(config)
        results = self._exec(sql, tuple(params))

        return {
            "title": "DRG费用排名",
            "columns": ["drg_code", "drg_desc", "mdc_code", "mdc_desc"] + metrics,
            "rows": results,
            "total": len(results)
        }

    def stay_comparison(self, group_by: str = "drg",
                        metrics: List[str] = None,
                        filters: Dict[str, Any] = None,
                        limit: int = 20) -> Dict[str, Any]:
        """住院天数对比"""
        if not metrics:
            metrics = ["avg_stay", "max_stay", "cases"]

        invalid_metrics = self.builder.validate_metrics(metrics)
        if invalid_metrics:
            raise ValueError(f"无效的指标: {invalid_metrics}")

        dimension_map = {
            "drg": ["drg_code", "drg_desc"],
            "diagnosis": ["diagnosis_code", "diagnosis_desc"],
            "severity": ["severity_code", "severity_desc"],
            "mdc": ["mdc_code", "mdc_desc"]
        }

        if group_by not in dimension_map:
            raise ValueError(f"无效的分组维度: {group_by}，可选值: {list(dimension_map.keys())}")

        dimensions = dimension_map[group_by]

        config = QueryConfig(
            dimensions=dimensions,
            metrics=metrics,
            filters=filters or {},
            sort={"field": "avg_stay", "order": "desc"},
            limit=limit
        )

        sql, params = self.builder.build_aggregate_query(config)
        results = self._exec(sql, tuple(params))

        return {
            "title": f"住院天数对比 - 按{group_by}分组",
            "group_by": group_by,
            "columns": dimensions + metrics,
            "rows": results,
            "total": len(results)
        }

    def mortality_risk_comparison(self, group_by: str = "risk_mortality",
                                  metrics: List[str] = None,
                                  filters: Dict[str, Any] = None) -> Dict[str, Any]:
        """死亡风险对比"""
        if not metrics:
            metrics = ["cases", "avg_charges", "avg_stay"]

        invalid_metrics = self.builder.validate_metrics(metrics)
        if invalid_metrics:
            raise ValueError(f"无效的指标: {invalid_metrics}")

        dimension_map = {
            "risk_mortality": ["risk_mortality"],
            "severity": ["severity_code", "severity_desc"],
            "mdc": ["mdc_code", "mdc_desc"],
            "drg": ["drg_code", "drg_desc"]
        }

        if group_by not in dimension_map:
            raise ValueError(f"无效的分组维度: {group_by}，可选值: {list(dimension_map.keys())}")

        dimensions = dimension_map[group_by]

        config = QueryConfig(
            dimensions=dimensions,
            metrics=metrics,
            filters=filters or {},
            sort={"field": "cases", "order": "desc"}
        )

        sql, params = self.builder.build_aggregate_query(config)
        results = self._exec(sql, tuple(params))

        total_cases = sum(row.get("cases", 0) for row in results if row.get("cases"))
        for row in results:
            cases = row.get("cases", 0)
            if total_cases > 0:
                row["percentage"] = round((cases / total_cases) * 100, 2)
            else:
                row["percentage"] = 0

        return {
            "title": f"死亡风险对比 - 按{group_by}分组",
            "group_by": group_by,
            "columns": dimensions + metrics + ["percentage"],
            "rows": results,
            "total": len(results),
            "total_cases": total_cases
        }

    def cmi_ranking(self, group_by: str = "drg",
                    filters: Dict[str, Any] = None,
                    limit: int = 20,
                    sort_order: str = "desc") -> Dict[str, Any]:
        """CMI排名 (Case Mix Index)"""
        dimension_map = {
            "drg": ["drg_code", "drg_desc"],
            "mdc": ["mdc_code", "mdc_desc"],
            "hospital": ["hospital_name", "hospital_area"]
        }

        if group_by not in dimension_map:
            raise ValueError(f"无效的分组维度: {group_by}，可选值: {list(dimension_map.keys())}")

        dimensions = dimension_map[group_by]
        metrics = ["cases", "avg_charges", "total_charges"]

        config = QueryConfig(
            dimensions=dimensions,
            metrics=metrics,
            filters=filters or {},
            sort={"field": "cases", "order": "desc"}
        )

        sql, params = self.builder.build_aggregate_query(config)
        results = self._exec(sql, tuple(params))

        total_cases = sum(float(row.get("cases", 0)) for row in results if row.get("cases"))
        total_charges = sum(float(row.get("total_charges", 0)) for row in results if row.get("total_charges"))
        overall_avg = total_charges / total_cases if total_cases > 0 else 0

        for row in results:
            avg_charges = float(row.get("avg_charges", 0))
            cases = float(row.get("cases", 0))
            if overall_avg > 0:
                row["cmi"] = round(avg_charges / overall_avg, 4)
            else:
                row["cmi"] = 0
            if total_cases > 0:
                row["weight_contribution"] = round((cases / total_cases) * row["cmi"], 4)
            else:
                row["weight_contribution"] = 0

        results.sort(key=lambda x: x.get("cmi", 0), reverse=(sort_order == "desc"))
        results = results[:limit]

        return {
            "title": f"CMI排名 - 按{group_by}分组",
            "group_by": group_by,
            "columns": dimensions + metrics + ["cmi", "weight_contribution"],
            "rows": results,
            "total": len(results),
            "overall_avg_charges": round(overall_avg, 2)
        }

    def outlier_detection(self, metric: str = "avg_charges",
                          group_by: str = "drg",
                          method: str = "iqr",
                          threshold: float = 1.5,
                          filters: Dict[str, Any] = None,
                          limit: int = 50) -> Dict[str, Any]:
        """离群识别"""
        if metric not in METRIC_MAP:
            raise ValueError(f"无效的指标: {metric}")

        dimension_map = {
            "drg": ["drg_code", "drg_desc"],
            "diagnosis": ["diagnosis_code", "diagnosis_desc"],
            "hospital": ["hospital_name", "hospital_area"]
        }

        if group_by not in dimension_map:
            raise ValueError(f"无效的分组维度: {group_by}，可选值: {list(dimension_map.keys())}")

        dimensions = dimension_map[group_by]
        metrics = ["cases", metric]

        config = QueryConfig(
            dimensions=dimensions,
            metrics=metrics,
            filters=filters or {},
            sort={"field": metric, "order": "desc"}
        )

        sql, params = self.builder.build_aggregate_query(config)
        results = self._exec(sql, tuple(params))

        values = [float(row.get(metric, 0)) for row in results if row.get(metric) is not None]

        if not values:
            return {
                "title": "离群识别", "method": method, "threshold": threshold,
                "outliers": [], "normal": [], "statistics": {}
            }

        import statistics
        mean_val = statistics.mean(values)
        median_val = statistics.median(values)
        std_val = statistics.stdev(values) if len(values) > 1 else 0

        sorted_vals = sorted(values)
        n = len(sorted_vals)
        q1 = sorted_vals[n // 4] if n >= 4 else sorted_vals[0]
        q3 = sorted_vals[3 * n // 4] if n >= 4 else sorted_vals[-1]
        iqr = q3 - q1

        outliers = []
        normal = []

        for row in results:
            val = float(row.get(metric, 0))
            is_outlier = False
            outlier_type = None

            if method == "iqr":
                lower_bound = q1 - threshold * iqr
                upper_bound = q3 + threshold * iqr
                if val < lower_bound:
                    is_outlier, outlier_type = True, "low"
                elif val > upper_bound:
                    is_outlier, outlier_type = True, "high"
            elif method == "zscore":
                if std_val > 0:
                    z_score = abs(val - mean_val) / std_val
                    if z_score > threshold:
                        is_outlier = True
                        outlier_type = "high" if val > mean_val else "low"

            row["outlier_type"] = outlier_type
            row["deviation"] = round(val - mean_val, 2)

            if is_outlier:
                outliers.append(row)
            else:
                normal.append(row)

        outliers.sort(key=lambda x: abs(x.get("deviation", 0)), reverse=True)

        return {
            "title": "离群识别", "method": method, "threshold": threshold,
            "metric": metric, "group_by": group_by,
            "outliers": outliers[:limit],
            "outlier_count": len(outliers), "normal_count": len(normal),
            "statistics": {
                "mean": round(mean_val, 2), "median": round(median_val, 2),
                "std": round(std_val, 2), "q1": round(q1, 2),
                "q3": round(q3, 2), "iqr": round(iqr, 2)
            }
        }

    def get_drg_summary(self, filters: Dict[str, Any] = None) -> Dict[str, Any]:
        """获取DRG汇总信息"""
        drg_count_sql = "SELECT COUNT(DISTINCT apr_drg_code) as count FROM dim_drg"
        drg_count = self._exec(drg_count_sql)[0].get("count", 0)

        # FORCE INDEX (idx_discharge_year)：用最小的二级索引扫全表，COUNT 不再回表。
        # 三个查询原各带 (SELECT COUNT(*) FROM fact_discharge) 子查询，每次都是一次
        # 千万行全表扫描；改为复用 summary 里的 total_cases 作分母。
        summary_sql = """
        SELECT
            COUNT(*) as total_cases,
            SUM(total_charges) as total_charges,
            AVG(length_of_stay) as avg_stay
        FROM fact_discharge FORCE INDEX (idx_discharge_year)
        """
        summary = self._exec(summary_sql)[0]
        total_cases = summary.get("total_cases", 0) or 1

        risk_sql = """
        SELECT
            f.apr_risk_mortality as risk,
            COUNT(*) as cases,
            ROUND(COUNT(*) * 100.0 / %s, 2) as percentage
        FROM fact_discharge f FORCE INDEX (idx_risk_mortality)
        GROUP BY f.apr_risk_mortality
        ORDER BY cases DESC
        """
        risk_dist = self._exec(risk_sql, (total_cases,))

        severity_sql = """
        SELECT
            f.apr_severity_desc as severity,
            COUNT(*) as cases,
            ROUND(COUNT(*) * 100.0 / %s, 2) as percentage
        FROM fact_discharge f FORCE INDEX (idx_severity_desc)
        GROUP BY f.apr_severity_desc
        ORDER BY cases DESC
        """
        severity_dist = self._exec(severity_sql, (total_cases,))

        return {
            "title": "DRG汇总信息",
            "total_drg": drg_count,
            "total_cases": summary.get("total_cases", 0),
            "total_charges": summary.get("total_charges", 0),
            "avg_stay": round(summary.get("avg_stay", 0), 2),
            "risk_distribution": risk_dist,
            "severity_distribution": severity_dist
        }


# 全局服务实例（默认MySQL）
drg_service = DRGService()
