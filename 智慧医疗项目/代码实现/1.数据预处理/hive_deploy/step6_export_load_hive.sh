#!/bin/bash
# 从WSL内部导出Windows MySQL数据到WSL文件系统，然后加载到Hive
set +e

source /etc/profile.d/hadoop-env.sh
export HADOOP_HOME=/opt/hadoop HIVE_HOME=/opt/hive

# Windows MySQL的IP (WSL2中Windows主机IP)
WIN_HOST=$(cat /etc/resolv.conf | grep nameserver | awk '{print $2}')
echo "=== Windows Host IP: $WIN_HOST ==="

# 测试连接Windows MySQL
echo "=== 测试连接Windows MySQL ==="
mysql -h "$WIN_HOST" -uroot -pCsu@Boy727620zy -P 3306 -e "SELECT COUNT(*) as total FROM medical_db.medical_data;" 2>&1 | grep -v "Warning"

if [ $? -ne 0 ]; then
    echo "[ERROR] 无法连接Windows MySQL ($WIN_HOST:3306)"
    echo "尝试其他IP..."
    # 尝试其他可能的网关IP
    for ip in $(ip route | grep default | awk '{print $3}'); do
        echo "  尝试 $ip..."
        mysql -h "$ip" -uroot -pCsu@Boy727620zy -P 3306 -e "SELECT 1;" 2>&1 | grep -v "Warning" && WIN_HOST=$ip && break
    done
fi

echo ""
echo "=== 1. 导出10,378,775行到 /data/medical_export.tsv ==="
echo "    源: Windows MySQL ($WIN_HOST:3306) medical_db.medical_data"
echo "    目标: /data/medical_export.tsv (WSL文件系统)"
mkdir -p /data
START=$(date +%s)

mysql -h "$WIN_HOST" --batch --raw --quick -uroot -pCsu@Boy727620zy medical_db \
  -e "SELECT * FROM medical_data" > /data/medical_export.tsv 2>/dev/null

ELAPSED=$(( $(date +%s) - START ))
FILESIZE=$(du -h /data/medical_export.tsv | cut -f1)
LINES=$(wc -l < /data/medical_export.tsv)
echo "  导出完成! 耗时: ${ELAPSED}s, 文件大小: $FILESIZE, 行数: $LINES"

echo ""
echo "=== 2. 在Hive中创建ODS层宽表 ==="
$HIVE_HOME/bin/beeline -u "jdbc:hive2://localhost:10000/default" -n luo \
  --hivevar hive.execution.engine=mr \
  -e "
CREATE DATABASE IF NOT EXISTS ods;
USE ods;
DROP TABLE IF EXISTS ods_medical_data;
CREATE TABLE ods_medical_data (
    id BIGINT,
    hospital_service_area STRING,
    hospital_county STRING,
    operating_certificate_number STRING,
    permanent_facility_id STRING,
    facility_name STRING,
    age_group STRING,
    zip_code_3digits STRING,
    gender STRING,
    race STRING,
    ethnicity STRING,
    length_of_stay INT,
    type_of_admission STRING,
    patient_disposition STRING,
    discharge_year INT,
    ccsr_diagnosis_code STRING,
    ccsr_diagnosis_description STRING,
    ccsr_procedure_code STRING,
    ccsr_procedure_description STRING,
    apr_drg_code INT,
    apr_drg_description STRING,
    apr_mdc_code INT,
    apr_mdc_description STRING,
    apr_severity_of_illness_code INT,
    apr_severity_of_illness_description STRING,
    apr_risk_of_mortality STRING,
    apr_medical_surgical_description STRING,
    payment_typology_1 STRING,
    payment_typology_2 STRING,
    payment_typology_3 STRING,
    birth_weight INT,
    emergency_department_indicator STRING,
    total_charges DOUBLE,
    total_costs DOUBLE
)
ROW FORMAT DELIMITED
    FIELDS TERMINATED BY '\t'
    LINES TERMINATED BY '\n'
STORED AS TEXTFILE
TBLPROPERTIES ('serialization.null.format'='NULL');
" 2>&1 | grep -vE 'SLF4J|binding|See http|Actual|^\s*$'

echo ""
echo "=== 3. LOAD DATA LOCAL INPATH ==="
START2=$(date +%s)
$HIVE_HOME/bin/beeline -u "jdbc:hive2://localhost:10000/default" -n luo \
  --hivevar hive.execution.engine=mr \
  -e "
USE ods;
LOAD DATA LOCAL INPATH '/data/medical_export.tsv' OVERWRITE INTO TABLE ods_medical_data;
" 2>&1 | grep -vE 'SLF4J|binding|See http|Actual|^\s*$'
ELAPSED2=$(( $(date +%s) - START2 ))
echo "  LOAD完成! 耗时: ${ELAPSED2}s"

echo ""
echo "=== 4. 验证行数 ==="
$HIVE_HOME/bin/beeline -u "jdbc:hive2://localhost:10000/default" -n luo \
  --hivevar hive.execution.engine=mr \
  -e "
USE ods;
SELECT COUNT(*) as total_rows FROM ods_medical_data;
SELECT discharge_year, COUNT(*) as cnt FROM ods_medical_data GROUP BY discharge_year ORDER BY discharge_year;
" 2>&1 | grep -vE 'SLF4J|binding|See http|Actual|^\s*$|WARNING|Stage|Time taken'

echo ""
echo "=== 5. 清理TSV文件释放空间 ==="
rm -f /data/medical_export.tsv
echo "  已删除 /data/medical_export.tsv"
df -h / | tail -1

echo ""
echo "[DONE] Step6: 数据迁移完成"
