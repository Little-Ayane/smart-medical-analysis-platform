#!/bin/bash
# ETL同步脚本：Spark SQL聚合 → MySQL结果表
# 用法：bash etl_sync.sh
# 建议每天凌晨运行一次（crontab）

set -e
export JAVA_HOME=/opt/bigdata/jdk1.8.0_212
export SPARK_HOME=/opt/bigdata/spark-3.3.1-bin-hadoop3
export PATH=$SPARK_HOME/bin:$PATH

SPARK_SQL="$SPARK_HOME/bin/spark-sql --master local[*]"
OUTPUT_DIR="/tmp/etl_results"
MYSQL_USER="root"
MYSQL_PASS="123456"
MYSQL_DB="medical_db"

mkdir -p $OUTPUT_DIR

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始ETL同步..."

# Spark SQL聚合并输出到本地目录
run_agg() {
    local name=$1
    local sql=$2
    echo "  聚合: $name..."
    $SPARK_SQL -e "
    USE medical_db;
    INSERT OVERWRITE LOCAL DIRECTORY '$OUTPUT_DIR/$name'
    ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t'
    $sql;
    " 2>/dev/null
}

run_agg "drg_cost" "
SELECT d.apr_drg_code, d.apr_drg_description, d.apr_mdc_code, d.apr_mdc_description,
       COUNT(*), CAST(SUM(f.total_charges) AS DECIMAL(15,2)), CAST(AVG(f.total_charges) AS DECIMAL(12,2)),
       CAST(SUM(f.total_costs) AS DECIMAL(15,2)), CAST(AVG(f.total_costs) AS DECIMAL(12,2)),
       CAST(AVG(f.length_of_stay) AS DECIMAL(8,2))
FROM fact_discharge f JOIN dim_drg d ON f.drg_id = d.drg_id
GROUP BY d.apr_drg_code, d.apr_drg_description, d.apr_mdc_code, d.apr_mdc_description
"

run_agg "hospital" "
SELECT h.hospital_id, h.facility_name, h.hospital_service_area, h.hospital_county,
       COUNT(*), CAST(SUM(f.total_charges) AS DECIMAL(15,2)), CAST(AVG(f.total_charges) AS DECIMAL(12,2)),
       CAST(AVG(f.length_of_stay) AS DECIMAL(8,2)),
       ROUND(SUM(CASE WHEN f.patient_disposition='Expired' THEN 1 ELSE 0 END)*100.0/COUNT(*), 2)
FROM fact_discharge f JOIN dim_hospital h ON f.hospital_id = h.hospital_id
GROUP BY h.hospital_id, h.facility_name, h.hospital_service_area, h.hospital_county
"

run_agg "diagnosis" "
SELECT d.diagnosis_id, d.ccsr_diagnosis_code, d.ccsr_diagnosis_description,
       COUNT(*), CAST(SUM(f.total_charges) AS DECIMAL(15,2)), CAST(AVG(f.total_charges) AS DECIMAL(12,2)),
       CAST(AVG(f.length_of_stay) AS DECIMAL(8,2))
FROM fact_discharge f JOIN dim_diagnosis d ON f.diagnosis_id = d.diagnosis_id
GROUP BY d.diagnosis_id, d.ccsr_diagnosis_code, d.ccsr_diagnosis_description
"

run_agg "mortality" "
SELECT d.apr_risk_of_mortality, COUNT(*),
       ROUND(COUNT(*)*100.0/(SELECT COUNT(*) FROM fact_discharge), 2),
       CAST(AVG(f.total_charges) AS DECIMAL(12,2)), CAST(AVG(f.length_of_stay) AS DECIMAL(8,2))
FROM fact_discharge f JOIN dim_drg d ON f.drg_id = d.drg_id
GROUP BY d.apr_risk_of_mortality ORDER BY COUNT(*) DESC
"

run_agg "severity" "
SELECT d.apr_severity_code, d.apr_severity_description, COUNT(*),
       ROUND(COUNT(*)*100.0/(SELECT COUNT(*) FROM fact_discharge), 2),
       CAST(AVG(f.total_charges) AS DECIMAL(12,2)), CAST(AVG(f.length_of_stay) AS DECIMAL(8,2))
FROM fact_discharge f JOIN dim_drg d ON f.drg_id = d.drg_id
GROUP BY d.apr_severity_code, d.apr_severity_description ORDER BY COUNT(*) DESC
"

run_agg "yearly" "
SELECT t.year_id, t.discharge_year, COUNT(*),
       CAST(SUM(f.total_charges) AS DECIMAL(15,2)), CAST(AVG(f.total_charges) AS DECIMAL(12,2)),
       CAST(SUM(f.total_costs) AS DECIMAL(15,2)), CAST(AVG(f.length_of_stay) AS DECIMAL(8,2))
FROM fact_discharge f JOIN dim_time t ON f.year_id = t.year_id
GROUP BY t.year_id, t.discharge_year ORDER BY t.discharge_year
"

run_agg "age" "
SELECT p.age_group, COUNT(*),
       ROUND(COUNT(*)*100.0/(SELECT COUNT(*) FROM fact_discharge), 2),
       CAST(AVG(f.total_charges) AS DECIMAL(12,2)), CAST(AVG(f.length_of_stay) AS DECIMAL(8,2))
FROM fact_discharge f JOIN dim_patient p ON f.patient_demo_id = p.patient_demo_id
GROUP BY p.age_group ORDER BY COUNT(*) DESC
"

run_agg "payment" "
SELECT p.payment_typology_1, COUNT(*),
       ROUND(COUNT(*)*100.0/(SELECT COUNT(*) FROM fact_discharge), 2),
       CAST(AVG(f.total_charges) AS DECIMAL(12,2))
FROM fact_discharge f JOIN dim_payment p ON f.payment_id = p.payment_id
GROUP BY p.payment_typology_1 ORDER BY COUNT(*) DESC
"

echo "  Spark聚合完成，导入MySQL..."

# 合并并导入MySQL
import_mysql() {
    local name=$1
    local table=$2
    local tmp="/tmp/etl_${name}.tsv"
    cat $OUTPUT_DIR/$name/part-* > $tmp 2>/dev/null

    if [ -s "$tmp" ]; then
        mysql -u $MYSQL_USER -p$MYSQL_PASS --local-infile=1 -e "
        USE $MYSQL_DB;
        TRUNCATE TABLE $table;
        LOAD DATA LOCAL INFILE '$tmp' INTO TABLE $table FIELDS TERMINATED BY '\t';
        " 2>/dev/null
        local cnt=$(mysql -u $MYSQL_USER -p$MYSQL_PASS -N -e "SELECT COUNT(*) FROM $MYSQL_DB.$table;" 2>/dev/null)
        echo "  ✅ $table: ${cnt}行"
    fi
}

import_mysql "drg_cost" "agg_drg_cost_ranking"
import_mysql "hospital" "agg_hospital_stats"
import_mysql "diagnosis" "agg_diagnosis_stats"
import_mysql "mortality" "agg_mortality_risk"
import_mysql "severity" "agg_severity_stats"
import_mysql "yearly" "agg_yearly_trend"
import_mysql "age" "agg_age_distribution"
import_mysql "payment" "agg_payment_stats"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ETL同步完成！"
