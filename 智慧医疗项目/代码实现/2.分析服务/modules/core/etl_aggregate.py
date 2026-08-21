"""
ETL聚合脚本：Spark SQL读Hive → 聚合计算 → 写入MySQL结果表
运行方式：python3.11 etl_aggregate.py
"""
import os
import sys
import time

# 设置环境变量
os.environ["JAVA_HOME"] = "/opt/bigdata/jdk1.8.0_212"
os.environ["SPARK_HOME"] = "/opt/bigdata/spark-3.3.1-bin-hadoop3"
os.environ["PYSPARK_PYTHON"] = sys.executable

from pyspark.sql import SparkSession

# MySQL连接配置
MYSQL_URL = "jdbc:mysql://localhost:3306/medical_db?useSSL=false&allowPublicKeyRetrieval=true"
MYSQL_PROPS = {
    "user": "root",
    "password": "123456",
    "driver": "com.mysql.cj.jdbc.Driver"
}


def create_spark_session():
    """创建Spark会话"""
    spark = SparkSession.builder \
        .appName("MedicalETL") \
        .master("local[*]") \
        .config("spark.sql.warehouse.dir", "hdfs://localhost:9000/user/hive/warehouse") \
        .config("spark.jars", "/opt/bigdata/mysql-connector-java-8.0.30.jar") \
        .enableHiveSupport() \
        .getOrCreate()
    # 设置日志级别
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def write_to_mysql(df, table_name, mode="overwrite"):
    """将DataFrame写入MySQL"""
    start = time.time()
    df.write.jdbc(url=MYSQL_URL, table=table_name, mode=mode, properties=MYSQL_PROPS)
    elapsed = time.time() - start
    print(f"  ✅ {table_name}: {df.count()}行, {elapsed:.1f}秒")


def aggregate_drg_cost(spark):
    """DRG费用排名聚合"""
    print("\n[1/8] DRG费用排名...")
    df = spark.sql("""
        SELECT
            d.apr_drg_code as drg_code,
            d.apr_drg_description as drg_description,
            d.apr_mdc_code as mdc_code,
            d.apr_mdc_description as mdc_description,
            COUNT(*) as cases,
            SUM(f.total_charges) as total_charges,
            AVG(f.total_charges) as avg_charges,
            SUM(f.total_costs) as total_costs,
            AVG(f.total_costs) as avg_costs,
            AVG(f.length_of_stay) as avg_stay
        FROM fact_discharge f
        JOIN dim_drg d ON f.drg_id = d.drg_id
        GROUP BY d.apr_drg_code, d.apr_drg_description,
                 d.apr_mdc_code, d.apr_mdc_description
        ORDER BY cases DESC
    """)
    write_to_mysql(df, "agg_drg_cost_ranking")


def aggregate_hospital_stats(spark):
    """医院维度统计"""
    print("\n[2/8] 医院统计...")
    df = spark.sql("""
        SELECT
            h.hospital_id,
            h.facility_name as hospital_name,
            h.hospital_service_area as hospital_area,
            h.hospital_county,
            COUNT(*) as cases,
            SUM(f.total_charges) as total_charges,
            AVG(f.total_charges) as avg_charges,
            AVG(f.length_of_stay) as avg_stay,
            ROUND(SUM(CASE WHEN f.patient_disposition = 'Expired' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as mortality_rate
        FROM fact_discharge f
        JOIN dim_hospital h ON f.hospital_id = h.hospital_id
        GROUP BY h.hospital_id, h.facility_name,
                 h.hospital_service_area, h.hospital_county
    """)
    write_to_mysql(df, "agg_hospital_stats")


def aggregate_diagnosis_stats(spark):
    """诊断维度统计"""
    print("\n[3/8] 诊断统计...")
    df = spark.sql("""
        SELECT
            d.diagnosis_id,
            d.ccsr_diagnosis_code as diagnosis_code,
            d.ccsr_diagnosis_description as diagnosis_description,
            COUNT(*) as cases,
            SUM(f.total_charges) as total_charges,
            AVG(f.total_charges) as avg_charges,
            AVG(f.length_of_stay) as avg_stay
        FROM fact_discharge f
        JOIN dim_diagnosis d ON f.diagnosis_id = d.diagnosis_id
        GROUP BY d.diagnosis_id, d.ccsr_diagnosis_code,
                 d.ccsr_diagnosis_description
    """)
    write_to_mysql(df, "agg_diagnosis_stats")


def aggregate_mortality_risk(spark):
    """死亡风险分布"""
    print("\n[4/8] 死亡风险分布...")
    df = spark.sql("""
        SELECT
            d.apr_risk_of_mortality as risk_level,
            COUNT(*) as cases,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM fact_discharge), 2) as percentage,
            AVG(f.total_charges) as avg_charges,
            AVG(f.length_of_stay) as avg_stay
        FROM fact_discharge f
        JOIN dim_drg d ON f.drg_id = d.drg_id
        GROUP BY d.apr_risk_of_mortality
        ORDER BY cases DESC
    """)
    write_to_mysql(df, "agg_mortality_risk")


def aggregate_severity_stats(spark):
    """严重程度分布"""
    print("\n[5/8] 严重程度分布...")
    df = spark.sql("""
        SELECT
            d.apr_severity_code as severity_code,
            d.apr_severity_description as severity_description,
            COUNT(*) as cases,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM fact_discharge), 2) as percentage,
            AVG(f.total_charges) as avg_charges,
            AVG(f.length_of_stay) as avg_stay
        FROM fact_discharge f
        JOIN dim_drg d ON f.drg_id = d.drg_id
        GROUP BY d.apr_severity_code, d.apr_severity_description
        ORDER BY cases DESC
    """)
    write_to_mysql(df, "agg_severity_stats")


def aggregate_yearly_trend(spark):
    """年度趋势"""
    print("\n[6/8] 年度趋势...")
    df = spark.sql("""
        SELECT
            t.year_id,
            t.discharge_year,
            COUNT(*) as cases,
            SUM(f.total_charges) as total_charges,
            AVG(f.total_charges) as avg_charges,
            SUM(f.total_costs) as total_costs,
            AVG(f.length_of_stay) as avg_stay
        FROM fact_discharge f
        JOIN dim_time t ON f.year_id = t.year_id
        GROUP BY t.year_id, t.discharge_year
        ORDER BY t.discharge_year
    """)
    write_to_mysql(df, "agg_yearly_trend")


def aggregate_age_distribution(spark):
    """年龄分布"""
    print("\n[7/8] 年龄分布...")
    df = spark.sql("""
        SELECT
            p.age_group,
            COUNT(*) as cases,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM fact_discharge), 2) as percentage,
            AVG(f.total_charges) as avg_charges,
            AVG(f.length_of_stay) as avg_stay
        FROM fact_discharge f
        JOIN dim_patient p ON f.patient_demo_id = p.patient_demo_id
        GROUP BY p.age_group
        ORDER BY cases DESC
    """)
    write_to_mysql(df, "agg_age_distribution")


def aggregate_payment_stats(spark):
    """支付方式分布"""
    print("\n[8/8] 支付方式分布...")
    df = spark.sql("""
        SELECT
            p.payment_typology_1 as payment_type,
            COUNT(*) as cases,
            ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM fact_discharge), 2) as percentage,
            AVG(f.total_charges) as avg_charges
        FROM fact_discharge f
        JOIN dim_payment p ON f.payment_id = p.payment_id
        GROUP BY p.payment_typology_1
        ORDER BY cases DESC
    """)
    write_to_mysql(df, "agg_payment_stats")


def main():
    """主函数"""
    print("=" * 60)
    print("  医疗数据 ETL 聚合任务")
    print("  Spark SQL → 聚合计算 → MySQL 结果表")
    print("=" * 60)

    start_total = time.time()

    # 创建Spark会话
    spark = create_spark_session()
    spark.sql("USE medical_db")

    # 执行所有聚合任务
    aggregate_drg_cost(spark)
    aggregate_hospital_stats(spark)
    aggregate_diagnosis_stats(spark)
    aggregate_mortality_risk(spark)
    aggregate_severity_stats(spark)
    aggregate_yearly_trend(spark)
    aggregate_age_distribution(spark)
    aggregate_payment_stats(spark)

    # 清理
    spark.stop()

    elapsed_total = time.time() - start_total
    print("\n" + "=" * 60)
    print(f"  ✅ 全部完成！总耗时: {elapsed_total:.1f}秒")
    print("=" * 60)


if __name__ == "__main__":
    main()
