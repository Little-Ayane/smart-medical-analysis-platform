#!/bin/bash
# ETL聚合脚本：Spark SQL → CSV → MySQL
# 用法：bash etl_aggregate.sh

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

echo "=========================================="
echo "  医疗数据 ETL 聚合任务"
echo "  Spark SQL → CSV → MySQL"
echo "=========================================="

# [1/8] DRG费用排名
echo ""
echo "[1/8] DRG费用排名..."
$SPARK_SQL -e "
USE medical_db;
INSERT OVERWRITE LOCAL DIRECTORY '$OUTPUT_DIR/drg_cost'
ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t'
SELECT
    d.apr_drg_code,
    d.apr_drg_description,
    d.apr_mdc_code,
    d.apr_mdc_description,
    COUNT(*),
    CAST(SUM(f.total_charges) AS DECIMAL(15,2)),
    CAST(AVG(f.total_charges) AS DECIMAL(12,2)),
    CAST(SUM(f.total_costs) AS DECIMAL(15,2)),
    CAST(AVG(f.total_costs) AS DECIMAL(12,2)),
    CAST(AVG(f.length_of_stay) AS DECIMAL(8,2))
FROM fact_discharge f
JOIN dim_drg d ON f.drg_id = d.drg_id
GROUP BY d.apr_drg_code, d.apr_drg_description,
         d.apr_mdc_code, d.apr_mdc_description;
" 2>/dev/null

# [2/8] 医院统计
echo "[2/8] 医院统计..."
$SPARK_SQL -e "
USE medical_db;
INSERT OVERWRITE LOCAL DIRECTORY '$OUTPUT_DIR/hospital'
ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t'
SELECT
    h.hospital_id,
    h.facility_name,
    h.hospital_service_area,
    h.hospital_county,
    COUNT(*),
    CAST(SUM(f.total_charges) AS DECIMAL(15,2)),
    CAST(AVG(f.total_charges) AS DECIMAL(12,2)),
    CAST(AVG(f.length_of_stay) AS DECIMAL(8,2)),
    ROUND(SUM(CASE WHEN f.patient_disposition = 'Expired' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2)
FROM fact_discharge f
JOIN dim_hospital h ON f.hospital_id = h.hospital_id
GROUP BY h.hospital_id, h.facility_name,
         h.hospital_service_area, h.hospital_county;
" 2>/dev/null

# [3/8] 诊断统计
echo "[3/8] 诊断统计..."
$SPARK_SQL -e "
USE medical_db;
INSERT OVERWRITE LOCAL DIRECTORY '$OUTPUT_DIR/diagnosis'
ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t'
SELECT
    d.diagnosis_id,
    d.ccsr_diagnosis_code,
    d.ccsr_diagnosis_description,
    COUNT(*),
    CAST(SUM(f.total_charges) AS DECIMAL(15,2)),
    CAST(AVG(f.total_charges) AS DECIMAL(12,2)),
    CAST(AVG(f.length_of_stay) AS DECIMAL(8,2))
FROM fact_discharge f
JOIN dim_diagnosis d ON f.diagnosis_id = d.diagnosis_id
GROUP BY d.diagnosis_id, d.ccsr_diagnosis_code,
         d.ccsr_diagnosis_description;
" 2>/dev/null

# [4/8] 死亡风险分布
echo "[4/8] 死亡风险分布..."
$SPARK_SQL -e "
USE medical_db;
INSERT OVERWRITE LOCAL DIRECTORY '$OUTPUT_DIR/mortality'
ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t'
SELECT
    d.apr_risk_of_mortality,
    COUNT(*),
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM fact_discharge), 2),
    CAST(AVG(f.total_charges) AS DECIMAL(12,2)),
    CAST(AVG(f.length_of_stay) AS DECIMAL(8,2))
FROM fact_discharge f
JOIN dim_drg d ON f.drg_id = d.drg_id
GROUP BY d.apr_risk_of_mortality
ORDER BY COUNT(*) DESC;
" 2>/dev/null

# [5/8] 严重程度分布
echo "[5/8] 严重程度分布..."
$SPARK_SQL -e "
USE medical_db;
INSERT OVERWRITE LOCAL DIRECTORY '$OUTPUT_DIR/severity'
ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t'
SELECT
    d.apr_severity_code,
    d.apr_severity_description,
    COUNT(*),
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM fact_discharge), 2),
    CAST(AVG(f.total_charges) AS DECIMAL(12,2)),
    CAST(AVG(f.length_of_stay) AS DECIMAL(8,2))
FROM fact_discharge f
JOIN dim_drg d ON f.drg_id = d.drg_id
GROUP BY d.apr_severity_code, d.apr_severity_description
ORDER BY COUNT(*) DESC;
" 2>/dev/null

# [6/8] 年度趋势
echo "[6/8] 年度趋势..."
$SPARK_SQL -e "
USE medical_db;
INSERT OVERWRITE LOCAL DIRECTORY '$OUTPUT_DIR/yearly'
ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t'
SELECT
    t.year_id,
    t.discharge_year,
    COUNT(*),
    CAST(SUM(f.total_charges) AS DECIMAL(15,2)),
    CAST(AVG(f.total_charges) AS DECIMAL(12,2)),
    CAST(SUM(f.total_costs) AS DECIMAL(15,2)),
    CAST(AVG(f.length_of_stay) AS DECIMAL(8,2))
FROM fact_discharge f
JOIN dim_time t ON f.year_id = t.year_id
GROUP BY t.year_id, t.discharge_year
ORDER BY t.discharge_year;
" 2>/dev/null

# [7/8] 年龄分布
echo "[7/8] 年龄分布..."
$SPARK_SQL -e "
USE medical_db;
INSERT OVERWRITE LOCAL DIRECTORY '$OUTPUT_DIR/age'
ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t'
SELECT
    p.age_group,
    COUNT(*),
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM fact_discharge), 2),
    CAST(AVG(f.total_charges) AS DECIMAL(12,2)),
    CAST(AVG(f.length_of_stay) AS DECIMAL(8,2))
FROM fact_discharge f
JOIN dim_patient p ON f.patient_demo_id = p.patient_demo_id
GROUP BY p.age_group
ORDER BY COUNT(*) DESC;
" 2>/dev/null

# [8/8] 支付方式分布
echo "[8/8] 支付方式分布..."
$SPARK_SQL -e "
USE medical_db;
INSERT OVERWRITE LOCAL DIRECTORY '$OUTPUT_DIR/payment'
ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t'
SELECT
    p.payment_typology_1,
    COUNT(*),
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM fact_discharge), 2),
    CAST(AVG(f.total_charges) AS DECIMAL(12,2))
FROM fact_discharge f
JOIN dim_payment p ON f.payment_id = p.payment_id
GROUP BY p.payment_typology_1
ORDER BY COUNT(*) DESC;
" 2>/dev/null

echo ""
echo "=========================================="
echo "  Spark 聚合完成，开始导入 MySQL..."
echo "=========================================="

# 合并part文件并导入MySQL
import_to_mysql() {
    local dir=$1
    local table=$2
    local tmp_file="/tmp/etl_${table}.tsv"

    # 合并所有part文件
    cat $dir/part-* > $tmp_file 2>/dev/null || true

    if [ -s "$tmp_file" ]; then
        # 清空旧数据
        mysql -u $MYSQL_USER -p$MYSQL_PASS -e "TRUNCATE TABLE $MYSQL_DB.$table;" 2>/dev/null

        # 导入新数据
        mysql -u $MYSQL_USER -p$MYSQL_PASS -e "
        LOAD DATA LOCAL INFILE '$tmp_file'
        INTO TABLE $MYSQL_DB.$table
        FIELDS TERMINATED BY '\t'
        LINES TERMINATED BY '\n';
        " 2>/dev/null

        local count=$(wc -l < $tmp_file)
        echo "  ✅ $table: ${count}行"
    else
        echo "  ❌ $table: 无数据"
    fi
}

import_to_mysql "$OUTPUT_DIR/drg_cost" "agg_drg_cost_ranking"
import_to_mysql "$OUTPUT_DIR/hospital" "agg_hospital_stats"
import_to_mysql "$OUTPUT_DIR/diagnosis" "agg_diagnosis_stats"
import_to_mysql "$OUTPUT_DIR/mortality" "agg_mortality_risk"
import_to_mysql "$OUTPUT_DIR/severity" "agg_severity_stats"
import_to_mysql "$OUTPUT_DIR/yearly" "agg_yearly_trend"
import_to_mysql "$OUTPUT_DIR/age" "agg_age_distribution"
import_to_mysql "$OUTPUT_DIR/payment" "agg_payment_stats"

echo ""
echo "=========================================="
echo "  ✅ 全部完成！"
echo "=========================================="
