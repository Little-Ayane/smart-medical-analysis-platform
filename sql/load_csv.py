# -*- coding: utf-8 -*-
"""
纪志鹏 · 简易 CSV -> smart_health 入库脚本（替代 LOAD DATA 的 Python 方案）
适用：当 VM 的 MySQL 未开启 local_infile、或想更稳妥地做字段映射/清洗时使用。
依赖：pip install pymysql
用法：
    python load_csv.py
默认读取 /home/jizhipeng/sample_10000_cleaned.csv，连接 127.0.0.1 的 smart_health。
如需改路径/账号，改下方 CONFIG（注意 password 要与 common.py 一致）。
"""
import csv
import sys

CONFIG = {
    "csv_path": "/home/jizhipeng/sample_10000_cleaned.csv",
    "host": "127.0.0.1",
    "user": "root",
    "password": "",          # ← 改成你 VM 的 MySQL root 密码（与 common.py 一致）
    "database": "smart_health",
    "charset": "utf8mb4",
}

FACT_INSERT = (
    "INSERT INTO fact_inpatient_discharge ("
    "facility_id, diagnosis_id, procedure_id, drg_id, age_group, zip3, gender, "
    "race, ethnicity, length_of_stay, type_of_admission, patient_disposition, "
    "discharge_year, apr_severity_code, apr_severity_desc, apr_risk_mortality, "
    "apr_medical_surgical, payment_typology_1, payment_typology_2, payment_typology_3, "
    "birth_weight, ed_indicator, total_charges, total_costs) "
    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
)


def to_int(v):
    v = (v or "").strip()
    return int(v) if v else None


def to_float(v):
    v = (v or "").strip()
    return float(v) if v else None


def main():
    try:
        import pymysql
    except ImportError:
        sys.exit("缺少 pymysql，请先执行：pip install pymysql")

    # ---- 第一遍：收集维度去重值，并暂存全部行 ----
    facilities = {}   # (ocn, pfid) -> (name, county, area)
    diagnoses = {}    # CODE -> desc
    procedures = {}   # CODE -> desc
    drgs = {}         # drg_code(int) -> (desc, mdc_code, mdc_desc)
    rows = []

    with open(CONFIG["csv_path"], encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append(r)
            ocn = (r.get("Operating Certificate Number") or "").strip()
            pfid = (r.get("Permanent Facility Id") or "").strip()
            fac_key = (ocn, pfid)
            if fac_key not in facilities:
                facilities[fac_key] = (
                    (r.get("Facility Name") or "").strip(),
                    (r.get("Hospital County") or "").strip(),
                    (r.get("Hospital Service Area") or "").strip(),
                )
            dx_code = (r.get("CCSR Diagnosis Code") or "").strip().upper()
            if dx_code and dx_code not in diagnoses:
                diagnoses[dx_code] = (r.get("CCSR Diagnosis Description") or "").strip()
            pr_code = (r.get("CCSR Procedure Code") or "").strip().upper()
            if pr_code and pr_code not in procedures:
                procedures[pr_code] = (r.get("CCSR Procedure Description") or "").strip()
            drg_code = to_int(r.get("APR DRG Code"))
            if drg_code is not None and drg_code not in drgs:
                drgs[drg_code] = (
                    (r.get("APR DRG Description") or "").strip(),
                    (r.get("APR MDC Code") or "").strip(),
                    (r.get("APR MDC Description") or "").strip(),
                )

    conn = pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **CONFIG)
    try:
        with conn.cursor() as cur:
            # ---- 写维度 ----
            cur.executemany(
                "INSERT IGNORE INTO dim_facility "
                "(operating_cert_number, permanent_facility_id, facility_name, hospital_county, service_area) "
                "VALUES (%s,%s,%s,%s,%s)",
                [(k[0], k[1], v[0], v[1], v[2]) for k, v in facilities.items()])
            cur.executemany(
                "INSERT IGNORE INTO dim_ccsr_diagnosis (ccsr_code, description) VALUES (%s,%s)",
                [(k, v) for k, v in diagnoses.items()])
            cur.executemany(
                "INSERT IGNORE INTO dim_ccsr_procedure (ccsr_code, description) VALUES (%s,%s)",
                [(k, v) for k, v in procedures.items()])
            cur.executemany(
                "INSERT IGNORE INTO dim_apr_drg (apr_drg_code, apr_drg_desc, apr_mdc_code, apr_mdc_desc) "
                "VALUES (%s,%s,%s,%s)",
                [(k, v[0], v[1], v[2]) for k, v in drgs.items()])
            conn.commit()

            # ---- 回读 id 映射 ----
            fac_map = {}
            cur.execute("SELECT facility_id, operating_cert_number, permanent_facility_id FROM dim_facility")
            for row in cur.fetchall():
                fac_map[(row["operating_cert_number"], row["permanent_facility_id"])] = row["facility_id"]
            dx_map = {}
            cur.execute("SELECT diagnosis_id, ccsr_code FROM dim_ccsr_diagnosis")
            for row in cur.fetchall():
                dx_map[row["ccsr_code"]] = row["diagnosis_id"]
            pr_map = {}
            cur.execute("SELECT procedure_id, ccsr_code FROM dim_ccsr_procedure")
            for row in cur.fetchall():
                pr_map[row["ccsr_code"]] = row["procedure_id"]
            drg_map = {}
            cur.execute("SELECT drg_id, apr_drg_code FROM dim_apr_drg")
            for row in cur.fetchall():
                drg_map[row["apr_drg_code"]] = row["drg_id"]

            # ---- 第二遍：写事实表（分批） ----
            BATCH = 1000
            buf = []
            total = 0
            for r in rows:
                ocn = (r.get("Operating Certificate Number") or "").strip()
                pfid = (r.get("Permanent Facility Id") or "").strip()
                fac_id = fac_map.get((ocn, pfid))
                dx_id = dx_map.get((r.get("CCSR Diagnosis Code") or "").strip().upper())
                pr_id = pr_map.get((r.get("CCSR Procedure Code") or "").strip().upper())
                drg_id = drg_map.get(to_int(r.get("APR DRG Code")))
                buf.append((
                    fac_id,
                    dx_id,
                    pr_id,
                    drg_id,
                    (r.get("Age Group") or "").strip() or None,
                    (r.get("Zip Code - 3 digits") or "").strip() or None,
                    (r.get("Gender") or "").strip() or None,
                    (r.get("Race") or "").strip() or None,
                    (r.get("Ethnicity") or "").strip() or None,
                    to_float(r.get("Length of Stay")),
                    (r.get("Type of Admission") or "").strip() or None,
                    (r.get("Patient Disposition") or "").strip() or None,
                    to_int(r.get("Discharge Year")),
                    to_int(r.get("APR Severity of Illness Code")),
                    (r.get("APR Severity of Illness Description") or "").strip() or None,
                    (r.get("APR Risk of Mortality") or "").strip() or None,
                    (r.get("APR Medical Surgical Description") or "").strip() or None,
                    (r.get("Payment Typology 1") or "").strip() or None,
                    (r.get("Payment Typology 2") or "").strip() or None,
                    (r.get("Payment Typology 3") or "").strip() or None,
                    to_float(r.get("Birth Weight")),
                    (r.get("Emergency Department Indicator") or "").strip() or None,
                    to_float(r.get("Total Charges")),
                    to_float(r.get("Total Costs")),
                ))
                if len(buf) >= BATCH:
                    cur.executemany(FACT_INSERT, buf)
                    total += len(buf)
                    buf.clear()
            if buf:
                cur.executemany(FACT_INSERT, buf)
                total += len(buf)
            conn.commit()
            print(f"done: {total} fact rows inserted; "
                  f"facility={len(facilities)} dx={len(diagnoses)} "
                  f"proc={len(procedures)} drg={len(drgs)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
