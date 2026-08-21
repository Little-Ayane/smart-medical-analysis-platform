"""
骆志远 - 超标识别（离群识别）+ 转归×急诊交叉
独立文件，不依赖 app.py 的导入（避免循环导入）
"""
import time
import pymysql
from flask import jsonify, request

# ===== 数据库连接（独立，不 import app）=====
def get_conn():
    return pymysql.connect(
        host="127.0.0.1",
        user="root",
        password="Csu@Boy727620zy",          # ← 改成你的 MySQL 密码！
        database="medical_db",
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )

def envelope(data, dimension=None, metric=None, total_records=None, query_ms=0):
    return {
        "code": 0,
        "message": "success",
        "data": data,
        "meta": {
            "dimension": dimension,
            "metric": metric,
            "total_records": total_records,
            "query_ms": query_ms,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    }

# ===== 注册路由 =====
def register_luo_routes(app):

    @app.route("/api/v1/analysis/outliers")
    def outliers():
        start = time.time()
        los_th = int(request.args.get("los_threshold", 30))
        charge_th = float(request.args.get("charge_threshold", 500000))

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                                    SELECT f.fact_id,
                                           h.facility_name,
                                           p.age_group, p.gender,
                                           f.emergency_department_indicator,
                                           f.length_of_stay,
                                           f.total_charges, f.total_costs,
                                           f.patient_disposition,
                                           d2.apr_severity_description AS severity_desc
                                    FROM fact_discharge f
                                    LEFT JOIN dim_hospital h ON f.hospital_id = h.hospital_id
                                    LEFT JOIN dim_patient p ON f.patient_demo_id = p.patient_demo_id
                                    LEFT JOIN dim_drg d2 ON f.drg_id = d2.drg_id
                                    WHERE f.length_of_stay > %s OR f.total_charges > %s
                                    ORDER BY f.length_of_stay DESC
                                    LIMIT 500
                                """, (los_th, charge_th))
                rows = cur.fetchall()
        finally:
            conn.close()

        return jsonify(envelope(rows, "outlier", "detail", len(rows),
                                int((time.time()-start)*1000)))

    @app.route("/api/v1/analysis/disposition/emergency-cross")
    def disposition_emergency_cross():
        start = time.time()
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT f.emergency_department_indicator AS is_emergency,
                           f.patient_disposition,
                           COUNT(*) AS cnt
                    FROM fact_discharge f
                    GROUP BY f.emergency_department_indicator, f.patient_disposition
                    ORDER BY cnt DESC
                """)
                rows = cur.fetchall()
        finally:
            conn.close()

        return jsonify(envelope(rows, "disposition_x_emergency", "count",
                                len(rows), int((time.time()-start)*1000)))