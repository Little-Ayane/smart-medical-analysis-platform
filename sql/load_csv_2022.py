# -*- coding: utf-8 -*-
"""
纪志鹏 · 2022 年住院数据追加入库（基于 load_csv.py 改造：流式、只追加、可断点验证）
- 数据源：Windows 上的 2022 SPARCS CSV（33 列，与既有 2021 数据同构）
- 目标：VM 上的 MySQL smart_health（fact_inpatient_discharge + 维度表，仅 INSERT，绝不 DROP/TRUNCATE）
- 只追加：默认检测若 fact 已存在 discharge_year=2022 的行则中止（--force 可覆盖重跑）
- 内存安全：两遍流式读取，不把整张表读进内存；金额字段自动去千分位逗号

用法：
  python load_csv_2022.py --dry-run        # 只解析 CSV，统计行数/维度/年份分布，不连库
  python load_csv_2022.py --limit 100      # 仅前 100 行真实入库（冒烟测试）
  python load_csv_2022.py                  # 全量入库
依赖：pip install pymysql
"""
import argparse
import csv
import sys

CONFIG = {
    "csv_path": r"D:\xwechat_files\wxid_k5avnjca724e22_0653\msg\file\2026-08\Downloads\Hospital_Inpatient_Discharges_(SPARCS_De-Identified)__2022_20260820.csv",
    "host": "192.168.111.141",
    "user": "root",
    "password": "root",
    "database": "smart_health",
    "charset": "utf8mb4",
    "port": 3306,
}

FACT_COLS = (
    "facility_id, diagnosis_id, procedure_id, drg_id, age_group, zip3, gender, "
    "race, ethnicity, length_of_stay, type_of_admission, patient_disposition, "
    "discharge_year, apr_severity_code, apr_severity_desc, apr_risk_mortality, "
    "apr_medical_surgical, payment_typology_1, payment_typology_2, payment_typology_3, "
    "birth_weight, ed_indicator, total_charges, total_costs"
)
FACT_INSERT = (
    "INSERT INTO fact_inpatient_discharge (" + FACT_COLS + ") "
    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
)


def to_int(v):
    v = (v or "").strip().replace(",", "")
    if not v:
        return None
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def to_float(v):
    v = (v or "").strip().replace(",", "").replace("$", "").replace("¥", "")
    if not v:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def stream_pass(csv_path, limit, on_row):
    """流式读取 CSV，对每一行调用 on_row(dict)。limit=None 表示全量。返回处理的数据行数。"""
    n = 0
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            on_row(r)
            n += 1
            if limit is not None and n >= limit:
                break
    return n


def _fact_tuple(r, fac_map, dx_map, pr_map, drg_map):
    return (
        fac_map.get(((r.get("Operating Certificate Number") or "").strip(),
                     (r.get("Permanent Facility Id") or "").strip())),
        dx_map.get((r.get("CCSR Diagnosis Code") or "").strip().upper()),
        pr_map.get((r.get("CCSR Procedure Code") or "").strip().upper()),
        drg_map.get(to_int(r.get("APR DRG Code"))),
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
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只解析统计，不连库")
    ap.add_argument("--limit", type=int, default=None, help="仅处理前 N 行（冒烟测试）")
    ap.add_argument("--force", action="store_true", help="即使已存在 2022 数据也继续")
    args = ap.parse_args()

    csv_path = CONFIG["csv_path"]
    print(f"[*] CSV: {csv_path}")

    # ---- Pass 1: 收集维度 + 统计 + 捕获首行样例 ----
    facilities, diagnoses, procedures, drgs = {}, {}, {}, {}
    year_counts = {}
    first_row = {}
    stats = {"rows": 0}

    def collect(r):
        stats["rows"] += 1
        if stats["rows"] == 1:
            first_row.update(r)
        ocn = (r.get("Operating Certificate Number") or "").strip()
        pfid = (r.get("Permanent Facility Id") or "").strip()
        fk = (ocn, pfid)
        if fk not in facilities:
            facilities[fk] = ((r.get("Facility Name") or "").strip(),
                              (r.get("Hospital County") or "").strip(),
                              (r.get("Hospital Service Area") or "").strip())
        dx = (r.get("CCSR Diagnosis Code") or "").strip().upper()
        if dx and dx not in diagnoses:
            diagnoses[dx] = (r.get("CCSR Diagnosis Description") or "").strip()
        pr = (r.get("CCSR Procedure Code") or "").strip().upper()
        if pr and pr not in procedures:
            procedures[pr] = (r.get("CCSR Procedure Description") or "").strip()
        dc = to_int(r.get("APR DRG Code"))
        if dc is not None and dc not in drgs:
            drgs[dc] = ((r.get("APR DRG Description") or "").strip(),
                        (r.get("APR MDC Code") or "").strip(),
                        (r.get("APR MDC Description") or "").strip())
        y = (r.get("Discharge Year") or "").strip()
        year_counts[y] = year_counts.get(y, 0) + 1

    n_parsed = stream_pass(csv_path, args.limit, collect)
    print(f"[*] 解析数据行数: {n_parsed}")
    print(f"[*] Discharge Year 分布: {year_counts}")
    print(f"[*] 维度规模: facility={len(facilities)} dx={len(diagnoses)} "
          f"proc={len(procedures)} drg={len(drgs)}")

    if first_row:
        sample = _fact_tuple(first_row,
                             {((first_row.get("Operating Certificate Number") or "").strip(),
                               (first_row.get("Permanent Facility Id") or "").strip()): 1},
                             {"X": 1}, {"X": 1}, {1: 1})
        print(f"[*] 首行映射样例(验证字段/金额去逗号): discharge_year={sample[12]}, "
              f"total_charges={sample[22]}, total_costs={sample[23]}, "
              f"facility_key={list(facilities)[0] if facilities else None}")

    if args.dry_run:
        print("[*] DRY-RUN 完成，未连接数据库。")
        return

    try:
        import pymysql
    except ImportError:
        sys.exit("缺少 pymysql，请先：pip install pymysql")

    conn = pymysql.connect(host=CONFIG["host"], port=CONFIG["port"], user=CONFIG["user"],
                           password=CONFIG["password"], database=CONFIG["database"],
                           charset=CONFIG["charset"], local_infile=True,
                           cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            # 安全闸门：若已存在 2022 数据
            cur.execute("SELECT COUNT(*) AS n FROM fact_inpatient_discharge WHERE discharge_year=2022")
            exist = cur.fetchone()["n"]
            if exist and not args.force:
                sys.exit(f"[!] fact 已存在 {exist} 行 discharge_year=2022，中止（用 --force 覆盖重跑）")
            if exist:
                print(f"[!] 检测到已存在 {exist} 行 2022，--force 继续（将产生重复，请知悉）")

            # 写维度（INSERT IGNORE，与既有 2021 维度天然去重）
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
            print("[*] 维度写入完成")

            # 回读 id 映射
            fac_map, dx_map, pr_map, drg_map = {}, {}, {}, {}
            cur.execute("SELECT facility_id, operating_cert_number, permanent_facility_id FROM dim_facility")
            for row in cur.fetchall():
                fac_map[(row["operating_cert_number"], row["permanent_facility_id"])] = row["facility_id"]
            cur.execute("SELECT diagnosis_id, ccsr_code FROM dim_ccsr_diagnosis")
            for row in cur.fetchall():
                dx_map[row["ccsr_code"]] = row["diagnosis_id"]
            cur.execute("SELECT procedure_id, ccsr_code FROM dim_ccsr_procedure")
            for row in cur.fetchall():
                pr_map[row["ccsr_code"]] = row["procedure_id"]
            cur.execute("SELECT drg_id, apr_drg_code FROM dim_apr_drg")
            for row in cur.fetchall():
                drg_map[row["apr_drg_code"]] = row["drg_id"]

            # Pass 2: 流式写事实表
            BATCH = 2000
            buf = []
            state = {"fact": 0}

            def insert_fact(r):
                buf.append(_fact_tuple(r, fac_map, dx_map, pr_map, drg_map))
                if len(buf) >= BATCH:
                    cur.executemany(FACT_INSERT, buf)
                    state["fact"] += len(buf)
                    buf.clear()
                    print(f"    ... 已写入 {state['fact']} 行", flush=True)

            stream_pass(csv_path, args.limit, insert_fact)
            if buf:
                cur.executemany(FACT_INSERT, buf)
                state["fact"] += len(buf)
            conn.commit()
            print(f"[OK] 事实表新增 {state['fact']} 行 (2022)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
