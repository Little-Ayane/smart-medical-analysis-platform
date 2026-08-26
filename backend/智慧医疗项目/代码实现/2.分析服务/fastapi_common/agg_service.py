"""
聚合结果查询服务
查询预聚合的结果表，毫秒级响应
"""
from typing import List, Dict, Any, Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from dao_factory import get_dao


class AggService:
    """聚合结果查询服务"""

    def __init__(self, data_source: str = None):
        self.dao = get_dao(data_source)

    def _exec(self, sql: str, params: tuple = None) -> List[Dict[str, Any]]:
        """执行查询"""
        return self.dao.execute_query(sql, params, use_cache=True)

    def get_drg_ranking(self, limit: int = 20, sort_by: str = "cases",
                        sort_order: str = "desc") -> Dict[str, Any]:
        """DRG费用排名（从结果表查询）"""
        order = "DESC" if sort_order == "desc" else "ASC"
        valid_sort = {"cases", "avg_charges", "total_charges", "avg_stay", "avg_costs"}
        if sort_by not in valid_sort:
            sort_by = "cases"

        sql = f"""
        SELECT drg_code, drg_description, mdc_code, mdc_description,
               cases, total_charges, avg_charges, total_costs, avg_costs, avg_stay
        FROM agg_drg_cost_ranking
        ORDER BY {sort_by} {order}
        LIMIT %s
        """
        results = self._exec(sql, (limit,))
        return {
            "title": "DRG费用排名",
            "columns": ["drg_code", "drg_description", "mdc_code", "mdc_description",
                        "cases", "total_charges", "avg_charges", "total_costs", "avg_costs", "avg_stay"],
            "rows": results,
            "total": len(results)
        }

    def get_hospital_stats(self, limit: int = 20, sort_by: str = "cases",
                           sort_order: str = "desc") -> Dict[str, Any]:
        """医院统计（从结果表查询）"""
        order = "DESC" if sort_order == "desc" else "ASC"
        valid_sort = {"cases", "avg_charges", "total_charges", "avg_stay", "mortality_rate"}
        if sort_by not in valid_sort:
            sort_by = "cases"

        sql = f"""
        SELECT hospital_id, hospital_name, hospital_area, hospital_county,
               cases, total_charges, avg_charges, avg_stay, mortality_rate
        FROM agg_hospital_stats
        ORDER BY {sort_by} {order}
        LIMIT %s
        """
        results = self._exec(sql, (limit,))
        return {
            "title": "医院统计",
            "rows": results,
            "total": len(results)
        }

    def get_diagnosis_stats(self, limit: int = 20, sort_by: str = "cases",
                            sort_order: str = "desc") -> Dict[str, Any]:
        """诊断统计（从结果表查询）"""
        order = "DESC" if sort_order == "desc" else "ASC"
        valid_sort = {"cases", "avg_charges", "total_charges", "avg_stay"}
        if sort_by not in valid_sort:
            sort_by = "cases"

        sql = f"""
        SELECT diagnosis_id, diagnosis_code, diagnosis_description,
               cases, total_charges, avg_charges, avg_stay
        FROM agg_diagnosis_stats
        ORDER BY {sort_by} {order}
        LIMIT %s
        """
        results = self._exec(sql, (limit,))
        return {
            "title": "诊断统计",
            "rows": results,
            "total": len(results)
        }

    def get_mortality_risk(self) -> Dict[str, Any]:
        """死亡风险分布（从结果表查询）"""
        sql = """
        SELECT risk_level, cases, percentage, avg_charges, avg_stay
        FROM agg_mortality_risk
        ORDER BY cases DESC
        """
        results = self._exec(sql)
        return {
            "title": "死亡风险分布",
            "rows": results,
            "total": len(results)
        }

    def get_severity_stats(self) -> Dict[str, Any]:
        """严重程度分布（从结果表查询）"""
        sql = """
        SELECT severity_code, severity_description, cases, percentage, avg_charges, avg_stay
        FROM agg_severity_stats
        ORDER BY cases DESC
        """
        results = self._exec(sql)
        return {
            "title": "严重程度分布",
            "rows": results,
            "total": len(results)
        }

    def get_yearly_trend(self) -> Dict[str, Any]:
        """年度趋势（从结果表查询）"""
        sql = """
        SELECT year_id, discharge_year, cases, total_charges, avg_charges, total_costs, avg_stay
        FROM agg_yearly_trend
        ORDER BY discharge_year
        """
        results = self._exec(sql)
        return {
            "title": "年度趋势",
            "rows": results,
            "total": len(results)
        }

    def get_age_distribution(self) -> Dict[str, Any]:
        """年龄分布（从结果表查询）"""
        sql = """
        SELECT age_group, cases, percentage, avg_charges, avg_stay
        FROM agg_age_distribution
        ORDER BY cases DESC
        """
        results = self._exec(sql)
        return {
            "title": "年龄分布",
            "rows": results,
            "total": len(results)
        }

    def get_payment_stats(self) -> Dict[str, Any]:
        """支付方式分布（从结果表查询）"""
        sql = """
        SELECT payment_type, cases, percentage, avg_charges
        FROM agg_payment_stats
        ORDER BY cases DESC
        """
        results = self._exec(sql)
        return {
            "title": "支付方式分布",
            "rows": results,
            "total": len(results)
        }

    def get_summary(self) -> Dict[str, Any]:
        """数据总览"""
        drg_count = self._exec("SELECT COUNT(*) as cnt FROM agg_drg_cost_ranking")[0]["cnt"]
        hospital_count = self._exec("SELECT COUNT(*) as cnt FROM agg_hospital_stats")[0]["cnt"]
        diagnosis_count = self._exec("SELECT COUNT(*) as cnt FROM agg_diagnosis_stats")[0]["cnt"]
        total_cases = self._exec("SELECT SUM(cases) as cnt FROM agg_yearly_trend")[0]["cnt"]

        return {
            "total_drg": drg_count,
            "total_hospitals": hospital_count,
            "total_diagnosis": diagnosis_count,
            "total_cases": total_cases,
            "data_source": "pre_aggregated (Spark SQL)"
        }


# 全局实例
agg_service = AggService()
