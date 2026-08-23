#!/bin/bash
# ==============================================================================
# Hive数仓分层一键构建脚本 (ODS→DWD→DWS→ADS)
# 适用于 智慧医疗大数据与AI大模型分析平台
# 运行环境: WSL2 Ubuntu (Hadoop 3.3.6 + Hive 3.1.3)
#
# 用法:
#   bash hive_warehouse_pipeline.sh           # 全量构建
#   bash hive_warehouse_pipeline.sh --stage dwd   # 只构建DWD层
#   bash hive_warehouse_pipeline.sh --stage dws   # 只构建DWS层
#   bash hive_warehouse_pipeline.sh --stage ads   # 只构建ADS层
#
# 说明: ODS层数据需先通过 step6_load_hive_ods.sh 加载完成
# ==============================================================================
source /etc/profile.d/hadoop-env.sh

HS2_URL="jdbc:hive2://localhost:10000/default"
HS2_USER="luo"
BEELINE="/opt/hive/bin/beeline"
STAGE="${2:-all}"

# ---------- 通用函数 ----------
run_sql() {
    local desc="$1"
    shift
    echo "======================================"
    echo "[$(date '+%H:%M:%S')] $desc"
    echo "======================================"
    timeout 3600 $BEELINE --outputformat=tsv2 -u "$HS2_URL" -n "$HS2_USER" -e "$@"
    local rc=$?
    if [ $rc -ne 0 ]; then
        echo "[ERROR] SQL执行失败: $desc (exit=$rc)"
        exit 1
    fi
    echo "[OK] $desc 完成"
}

# ---------- 检查服务 ----------
check_services() {
    echo "=== 检查Hive服务 ==="
    for port in 9083 10000; do
        (echo > /dev/tcp/127.0.0.1/$port) 2>/dev/null && echo "  Port $port OK" || { echo "  Port $port DOWN! 请先运行 start_all.sh"; exit 1; }
    done
}

# ---------- 1. DWD明细层 ----------
build_dwd() {
    run_sql "创建DWD数据库" "CREATE DATABASE IF NOT EXISTS dwd;"

    run_sql "创建DWD明细表 dwd_discharge_detail" "
        DROP TABLE IF EXISTS dwd.dwd_discharge_detail;
        CREATE TABLE dwd.dwd_discharge_detail (
            id BIGINT,
            age_group STRING,
            gender STRING,
            race STRING,
            ethnicity STRING,
            zip_code_3digits STRING,
            hospital_service_area STRING,
            hospital_county STRING,
            facility_name STRING,
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
            total_costs DOUBLE,
            cost_per_day DOUBLE,
            charge_cost_ratio DOUBLE
        ) STORED AS ORC;"

    run_sql "装载DWD明细数据 (清洗+派生字段)" "
        INSERT OVERWRITE TABLE dwd.dwd_discharge_detail
        SELECT
            id, age_group, gender, race, ethnicity, zip_code_3digits,
            hospital_service_area, hospital_county, facility_name,
            length_of_stay, type_of_admission, patient_disposition, discharge_year,
            ccsr_diagnosis_code, ccsr_diagnosis_description,
            ccsr_procedure_code, ccsr_procedure_description,
            apr_drg_code, apr_drg_description, apr_mdc_code, apr_mdc_description,
            apr_severity_of_illness_code, apr_severity_of_illness_description,
            apr_risk_of_mortality, apr_medical_surgical_description,
            payment_typology_1, payment_typology_2, payment_typology_3,
            birth_weight, emergency_department_indicator,
            total_charges, total_costs,
            CASE WHEN length_of_stay > 0 THEN ROUND(total_costs / length_of_stay, 2) ELSE NULL END,
            CASE WHEN total_costs > 0 THEN ROUND(total_charges / total_costs, 2) ELSE NULL END
        FROM ods.ods_medical_data;"

    echo "[DONE] DWD层构建完成"
}

# ---------- 2. DWS汇总层 ----------
build_dws() {
    run_sql "创建DWS数据库" "CREATE DATABASE IF NOT EXISTS dws;"

    run_sql "创建DWS多维汇总表 dws_discharge_summary" "
        DROP TABLE IF EXISTS dws.dws_discharge_summary;
        CREATE TABLE dws.dws_discharge_summary (
            discharge_year INT,
            hospital_service_area STRING,
            age_group STRING,
            gender STRING,
            apr_mdc_code INT,
            apr_mdc_description STRING,
            apr_severity_of_illness_code INT,
            apr_severity_of_illness_description STRING,
            discharge_count BIGINT,
            total_charges DOUBLE,
            total_costs DOUBLE,
            avg_length_of_stay DOUBLE,
            avg_cost_per_day DOUBLE,
            emergency_count BIGINT
        ) STORED AS ORC;"

    run_sql "创建DWS年度统计表 dws_yearly_stats" "
        DROP TABLE IF EXISTS dws.dws_yearly_stats;
        CREATE TABLE dws.dws_yearly_stats (
            discharge_year INT,
            discharge_count BIGINT,
            total_charges DOUBLE,
            total_costs DOUBLE,
            avg_charges DOUBLE,
            avg_costs DOUBLE,
            avg_length_of_stay DOUBLE
        ) STORED AS ORC;"

    run_sql "装载DWS多维汇总数据" "
        INSERT OVERWRITE TABLE dws.dws_discharge_summary
        SELECT
            discharge_year, hospital_service_area, age_group, gender,
            apr_mdc_code, MAX(apr_mdc_description),
            apr_severity_of_illness_code, MAX(apr_severity_of_illness_description),
            COUNT(*) AS discharge_count,
            SUM(total_charges) AS total_charges,
            SUM(total_costs) AS total_costs,
            ROUND(AVG(length_of_stay), 2) AS avg_length_of_stay,
            ROUND(AVG(cost_per_day), 2) AS avg_cost_per_day,
            SUM(CASE WHEN emergency_department_indicator = 'Y' THEN 1 ELSE 0 END) AS emergency_count
        FROM dwd.dwd_discharge_detail
        GROUP BY discharge_year, hospital_service_area, age_group, gender,
                 apr_mdc_code, apr_severity_of_illness_code;"

    run_sql "装载DWS年度统计数据" "
        INSERT OVERWRITE TABLE dws.dws_yearly_stats
        SELECT
            discharge_year, COUNT(*), SUM(total_charges), SUM(total_costs),
            ROUND(AVG(total_charges), 2), ROUND(AVG(total_costs), 2),
            ROUND(AVG(length_of_stay), 2)
        FROM dwd.dwd_discharge_detail
        GROUP BY discharge_year;"

    echo "[DONE] DWS层构建完成"
}

# ---------- 3. ADS应用层 ----------
build_ads() {
    run_sql "创建ADS数据库" "CREATE DATABASE IF NOT EXISTS ads;"

    run_sql "创建ADS年度总览表" "
        DROP TABLE IF EXISTS ads.ads_yearly_overview;
        CREATE TABLE ads.ads_yearly_overview (
            discharge_year INT, discharge_count BIGINT,
            total_charges DOUBLE, total_costs DOUBLE,
            avg_charges DOUBLE, avg_costs DOUBLE, avg_length_of_stay DOUBLE,
            yoy_count_growth DOUBLE, yoy_cost_growth DOUBLE
        ) STORED AS ORC;"

    run_sql "创建ADS医院服务区统计表" "
        DROP TABLE IF EXISTS ads.ads_hospital_area_stats;
        CREATE TABLE ads.ads_hospital_area_stats (
            discharge_year INT, hospital_service_area STRING,
            discharge_count BIGINT, total_costs DOUBLE,
            avg_costs DOUBLE, cost_share DOUBLE
        ) STORED AS ORC;"

    run_sql "创建ADS疾病分类分析表" "
        DROP TABLE IF EXISTS ads.ads_diagnosis_analysis;
        CREATE TABLE ads.ads_diagnosis_analysis (
            discharge_year INT, apr_mdc_code INT, apr_mdc_description STRING,
            discharge_count BIGINT, total_costs DOUBLE,
            avg_costs DOUBLE, case_share DOUBLE
        ) STORED AS ORC;"

    run_sql "创建ADS患者特征分析表" "
        DROP TABLE IF EXISTS ads.ads_patient_profile;
        CREATE TABLE ads.ads_patient_profile (
            discharge_year INT, age_group STRING, gender STRING,
            discharge_count BIGINT, total_costs DOUBLE,
            avg_costs DOUBLE, patient_share DOUBLE
        ) STORED AS ORC;"

    run_sql "装载ADS年度总览(含环比)" "
        INSERT OVERWRITE TABLE ads.ads_yearly_overview
        SELECT
            y1.discharge_year, y1.discharge_count, y1.total_charges, y1.total_costs,
            y1.avg_charges, y1.avg_costs, y1.avg_length_of_stay,
            ROUND((y1.discharge_count - y0.discharge_count) * 100.0 / y0.discharge_count, 2),
            ROUND((y1.total_costs - y0.total_costs) * 100.0 / y0.total_costs, 2)
        FROM dws.dws_yearly_stats y1
        LEFT JOIN dws.dws_yearly_stats y0 ON y1.discharge_year = y0.discharge_year + 1
        ORDER BY y1.discharge_year;"

    run_sql "装载ADS医院服务区统计" "
        INSERT OVERWRITE TABLE ads.ads_hospital_area_stats
        SELECT
            discharge_year, hospital_service_area,
            SUM(discharge_count), SUM(total_costs),
            ROUND(SUM(total_costs) / SUM(discharge_count), 2),
            ROUND(SUM(total_costs) * 100.0 /
                (SELECT SUM(total_costs) FROM dws.dws_discharge_summary s2
                 WHERE s2.discharge_year = s1.discharge_year), 2)
        FROM dws.dws_discharge_summary s1
        GROUP BY discharge_year, hospital_service_area
        ORDER BY discharge_year, total_costs DESC;"

    run_sql "装载ADS疾病分类分析" "
        INSERT OVERWRITE TABLE ads.ads_diagnosis_analysis
        SELECT
            discharge_year, apr_mdc_code, apr_mdc_description,
            SUM(discharge_count), SUM(total_costs),
            ROUND(SUM(total_costs) / SUM(discharge_count), 2),
            ROUND(SUM(discharge_count) * 100.0 /
                (SELECT SUM(discharge_count) FROM dws.dws_discharge_summary s2
                 WHERE s2.discharge_year = s1.discharge_year), 2)
        FROM dws.dws_discharge_summary s1
        GROUP BY discharge_year, apr_mdc_code, apr_mdc_description
        ORDER BY discharge_year, discharge_count DESC;"

    run_sql "装载ADS患者特征分析" "
        INSERT OVERWRITE TABLE ads.ads_patient_profile
        SELECT
            discharge_year, age_group, gender,
            SUM(discharge_count), SUM(total_costs),
            ROUND(SUM(total_costs) / SUM(discharge_count), 2),
            ROUND(SUM(discharge_count) * 100.0 /
                (SELECT SUM(discharge_count) FROM dws.dws_discharge_summary s2
                 WHERE s2.discharge_year = s1.discharge_year), 2)
        FROM dws.dws_discharge_summary s1
        GROUP BY discharge_year, age_group, gender
        ORDER BY discharge_year, discharge_count DESC;"

    echo "[DONE] ADS层构建完成"
}

# ---------- 4. 验证 ----------
verify() {
    echo "======================================"
    echo "[$(date '+%H:%M:%S')] 验证各层数据量"
    echo "======================================"
    run_sql "ODS层行数" "SELECT 'ods_medical_data' AS tbl, COUNT(*) AS cnt FROM ods.ods_medical_data;"
    run_sql "DWD层行数" "SELECT 'dwd_discharge_detail' AS tbl, COUNT(*) AS cnt FROM dwd.dwd_discharge_detail;"
    run_sql "DWS汇总行数" "SELECT 'dws_discharge_summary' AS tbl, COUNT(*) AS cnt FROM dws.dws_discharge_summary;"
    run_sql "ADS年度总览" "
        SELECT discharge_year, discharge_count,
               ROUND(total_costs/1e9, 2) AS cost_billions, avg_costs
        FROM ads.ads_yearly_overview ORDER BY discharge_year;"
}

# ---------- 主流程 ----------
check_services

case "$STAGE" in
    all)  build_dwd; build_dws; build_ads; verify ;;
    dwd)  build_dwd ;;
    dws)  build_dws ;;
    ads)  build_ads ;;
    *)    echo "用法: $0 [--stage all|dwd|dws|ads]"; exit 1 ;;
esac

echo ""
echo "=================== 数仓构建完成 ==================="
echo "表结构总览:"
echo "  ODS: ods.ods_medical_data (原始数据)"
echo "  DWD: dwd.dwd_discharge_detail (清洗明细)"
echo "  DWS: dws.dws_discharge_summary / dws.dws_yearly_stats (汇总)"
echo "  ADS: ads.ads_yearly_overview / ads_hospital_area_stats /"
echo "       ads_diagnosis_analysis / ads_patient_profile (应用)"
echo "====================================================="
