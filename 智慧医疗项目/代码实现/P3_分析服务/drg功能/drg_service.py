"""
DRG分析服务层
负责DRG相关的分析功能：费用排名、住院天数对比、死亡风险对比、CMI排名、离群识别
"""
from typing import List, Dict, Any, Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from mysql_dao import mysql_dao
from sql_builder import sql_builder, QueryConfig, DIMENSION_MAP, METRIC_MAP


class DRGService:
    """DRG分析服务类"""

    def __init__(self):
        self.dao = mysql_dao
        self.builder = sql_builder

    def drg_cost_ranking(self, metrics: List[str] = None,
                         filters: Dict[str, Any] = None,
                         limit: int = 20,
                         sort_order: str = "desc") -> Dict[str, Any]:
        """
        DRG费用排名

        Args:
            metrics: 指标列表，默认为病例数、总费用、平均费用
            filters: 筛选条件
            limit: 返回条数
            sort_order: 排序方式 (desc/asc)

        Returns:
            DRG费用排名结果
        """
        # 默认指标
        if not metrics:
            metrics = ["cases", "total_charges", "avg_charges"]

        # 验证指标
        invalid_metrics = self.builder.validate_metrics(metrics)
        if invalid_metrics:
            raise ValueError(f"无效的指标: {invalid_metrics}")

        # 构建查询配置 - 按DRG分组
        config = QueryConfig(
            dimensions=["drg_code", "drg_desc", "mdc_code", "mdc_desc"],
            metrics=metrics,
            filters=filters or {},
            sort={"field": metrics[0] if metrics else "cases", "order": sort_order},
            limit=limit
        )

        # 执行查询
        sql, params = self.builder.build_aggregate_query(config)
        results = self.dao.execute_query(sql, tuple(params))

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
        """
        住院天数对比

        Args:
            group_by: 分组维度 (drg/diagnosis/severity/mdc)
            metrics: 指标列表，默认为平均住院天数、最大住院天数、病例数
            filters: 筛选条件
            limit: 返回条数

        Returns:
            住院天数对比结果
        """
        # 默认指标
        if not metrics:
            metrics = ["avg_stay", "max_stay", "cases"]

        # 验证指标
        invalid_metrics = self.builder.validate_metrics(metrics)
        if invalid_metrics:
            raise ValueError(f"无效的指标: {invalid_metrics}")

        # 根据分组维度选择维度
        dimension_map = {
            "drg": ["drg_code", "drg_desc"],
            "diagnosis": ["diagnosis_code", "diagnosis_desc"],
            "severity": ["severity_code", "severity_desc"],
            "mdc": ["mdc_code", "mdc_desc"]
        }

        if group_by not in dimension_map:
            raise ValueError(f"无效的分组维度: {group_by}，可选值: {list(dimension_map.keys())}")

        dimensions = dimension_map[group_by]

        # 构建查询配置
        config = QueryConfig(
            dimensions=dimensions,
            metrics=metrics,
            filters=filters or {},
            sort={"field": "avg_stay", "order": "desc"},
            limit=limit
        )

        # 执行查询
        sql, params = self.builder.build_aggregate_query(config)
        results = self.dao.execute_query(sql, tuple(params))

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
        """
        死亡风险对比

        Args:
            group_by: 分组维度 (risk_mortality/severity/mdc/drg)
            metrics: 指标列表，默认为病例数、平均费用、平均住院天数
            filters: 筛选条件

        Returns:
            死亡风险对比结果
        """
        # 默认指标
        if not metrics:
            metrics = ["cases", "avg_charges", "avg_stay"]

        # 验证指标
        invalid_metrics = self.builder.validate_metrics(metrics)
        if invalid_metrics:
            raise ValueError(f"无效的指标: {invalid_metrics}")

        # 根据分组维度选择维度
        dimension_map = {
            "risk_mortality": ["risk_mortality"],
            "severity": ["severity_code", "severity_desc"],
            "mdc": ["mdc_code", "mdc_desc"],
            "drg": ["drg_code", "drg_desc"]
        }

        if group_by not in dimension_map:
            raise ValueError(f"无效的分组维度: {group_by}，可选值: {list(dimension_map.keys())}")

        dimensions = dimension_map[group_by]

        # 构建查询配置
        config = QueryConfig(
            dimensions=dimensions,
            metrics=metrics,
            filters=filters or {},
            sort={"field": "cases", "order": "desc"}
        )

        # 执行查询
        sql, params = self.builder.build_aggregate_query(config)
        results = self.dao.execute_query(sql, tuple(params))

        # 计算占比
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
        """
        CMI排名 (Case Mix Index - 病例组合指数)

        CMI = 某DRG的权重 × 该DRG的病例数 / 总病例数
        这里简化为按费用权重计算

        Args:
            group_by: 分组维度 (drg/mdc/hospital)
            filters: 筛选条件
            limit: 返回条数
            sort_order: 排序方式 (desc/asc)

        Returns:
            CMI排名结果
        """
        # 根据分组维度选择维度
        dimension_map = {
            "drg": ["drg_code", "drg_desc"],
            "mdc": ["mdc_code", "mdc_desc"],
            "hospital": ["hospital_name", "hospital_area"]
        }

        if group_by not in dimension_map:
            raise ValueError(f"无效的分组维度: {group_by}，可选值: {list(dimension_map.keys())}")

        dimensions = dimension_map[group_by]

        # 查询费用相关指标来计算CMI
        metrics = ["cases", "avg_charges", "total_charges"]

        # 构建查询配置
        config = QueryConfig(
            dimensions=dimensions,
            metrics=metrics,
            filters=filters or {},
            sort={"field": "cases", "order": "desc"}
        )

        # 执行查询
        sql, params = self.builder.build_aggregate_query(config)
        results = self.dao.execute_query(sql, tuple(params))

        # 计算CMI (简化版：平均费用 / 全体平均费用)
        total_cases = sum(float(row.get("cases", 0)) for row in results if row.get("cases"))
        total_charges = sum(float(row.get("total_charges", 0)) for row in results if row.get("total_charges"))

        # 全体平均费用
        overall_avg = total_charges / total_cases if total_cases > 0 else 0

        # 计算每个分组的CMI
        for row in results:
            avg_charges = float(row.get("avg_charges", 0))
            cases = float(row.get("cases", 0))

            # CMI = 该组平均费用 / 全体平均费用
            if overall_avg > 0:
                row["cmi"] = round(avg_charges / overall_avg, 4)
            else:
                row["cmi"] = 0

            # 计算权重贡献
            if total_cases > 0:
                row["weight_contribution"] = round((cases / total_cases) * row["cmi"], 4)
            else:
                row["weight_contribution"] = 0

        # 按CMI排序
        results.sort(key=lambda x: x.get("cmi", 0), reverse=(sort_order == "desc"))

        # 限制返回数量
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
        """
        离群识别

        Args:
            metric: 检测指标 (avg_charges/avg_stay/cases)
            group_by: 分组维度 (drg/diagnosis/hospital)
            method: 检测方法 (iqr/zscore)
            threshold: 阈值 (IQR倍数或Z分数)
            filters: 筛选条件
            limit: 返回条数

        Returns:
            离群识别结果
        """
        # 验证指标
        if metric not in METRIC_MAP:
            raise ValueError(f"无效的指标: {metric}")

        # 根据分组维度选择维度
        dimension_map = {
            "drg": ["drg_code", "drg_desc"],
            "diagnosis": ["diagnosis_code", "diagnosis_desc"],
            "hospital": ["hospital_name", "hospital_area"]
        }

        if group_by not in dimension_map:
            raise ValueError(f"无效的分组维度: {group_by}，可选值: {list(dimension_map.keys())}")

        dimensions = dimension_map[group_by]

        # 查询数据
        metrics = ["cases", metric]

        config = QueryConfig(
            dimensions=dimensions,
            metrics=metrics,
            filters=filters or {},
            sort={"field": metric, "order": "desc"}
        )

        sql, params = self.builder.build_aggregate_query(config)
        results = self.dao.execute_query(sql, tuple(params))

        # 提取指标值用于计算
        values = [float(row.get(metric, 0)) for row in results if row.get(metric) is not None]

        if not values:
            return {
                "title": "离群识别",
                "method": method,
                "threshold": threshold,
                "outliers": [],
                "normal": [],
                "statistics": {}
            }

        # 计算统计值
        import statistics
        mean_val = statistics.mean(values)
        median_val = statistics.median(values)
        std_val = statistics.stdev(values) if len(values) > 1 else 0

        # 计算IQR
        sorted_vals = sorted(values)
        n = len(sorted_vals)
        q1 = sorted_vals[n // 4] if n >= 4 else sorted_vals[0]
        q3 = sorted_vals[3 * n // 4] if n >= 4 else sorted_vals[-1]
        iqr = q3 - q1

        # 识别离群值
        outliers = []
        normal = []

        for row in results:
            val = float(row.get(metric, 0))
            is_outlier = False
            outlier_type = None

            if method == "iqr":
                # IQR方法
                lower_bound = q1 - threshold * iqr
                upper_bound = q3 + threshold * iqr
                if val < lower_bound:
                    is_outlier = True
                    outlier_type = "low"
                elif val > upper_bound:
                    is_outlier = True
                    outlier_type = "high"
            elif method == "zscore":
                # Z分数方法
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

        # 按偏差排序
        outliers.sort(key=lambda x: abs(x.get("deviation", 0)), reverse=True)

        return {
            "title": "离群识别",
            "method": method,
            "threshold": threshold,
            "metric": metric,
            "group_by": group_by,
            "outliers": outliers[:limit],
            "outlier_count": len(outliers),
            "normal_count": len(normal),
            "statistics": {
                "mean": round(mean_val, 2),
                "median": round(median_val, 2),
                "std": round(std_val, 2),
                "q1": round(q1, 2),
                "q3": round(q3, 2),
                "iqr": round(iqr, 2)
            }
        }

    def get_drg_summary(self, filters: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        获取DRG汇总信息

        Returns:
            DRG汇总统计
        """
        # 查询总DRG数
        drg_count_sql = "SELECT COUNT(DISTINCT apr_drg_code) as count FROM dim_drg"
        drg_count = self.dao.execute_query(drg_count_sql)[0].get("count", 0)

        # 查询总病例数和费用
        summary_sql = """
        SELECT
            COUNT(*) as total_cases,
            SUM(total_charges) as total_charges,
            AVG(length_of_stay) as avg_stay
        FROM fact_discharge
        """
        summary = self.dao.execute_query(summary_sql)[0]

        # 按死亡风险统计
        risk_sql = """
        SELECT
            d.apr_risk_of_mortality as risk,
            COUNT(*) as cases,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM fact_discharge), 2) as percentage
        FROM fact_discharge f
        JOIN dim_drg d ON f.drg_id = d.drg_id
        GROUP BY d.apr_risk_of_mortality
        ORDER BY cases DESC
        """
        risk_dist = self.dao.execute_query(risk_sql)

        # 按严重程度统计
        severity_sql = """
        SELECT
            d.apr_severity_description as severity,
            COUNT(*) as cases,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM fact_discharge), 2) as percentage
        FROM fact_discharge f
        JOIN dim_drg d ON f.drg_id = d.drg_id
        GROUP BY d.apr_severity_description
        ORDER BY cases DESC
        """
        severity_dist = self.dao.execute_query(severity_sql)

        return {
            "title": "DRG汇总信息",
            "total_drg": drg_count,
            "total_cases": summary.get("total_cases", 0),
            "total_charges": summary.get("total_charges", 0),
            "avg_stay": round(summary.get("avg_stay", 0), 2),
            "risk_distribution": risk_dist,
            "severity_distribution": severity_dist
        }


# 全局服务实例
drg_service = DRGService()
