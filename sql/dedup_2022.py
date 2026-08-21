# -*- coding: utf-8 -*-
"""去重 2022（后台运行）：建结构相同的干净表 -> 灌入 2021 全量 + 2022 去重 -> 原子改名。
只删完全重复行；差异行全部保留。日志写 dedup_2022.log。"""
import pymysql, time, sys

LOG = "F:/CSUProgram/smart-medical-analysis-platform/sql/dedup_2022.log"
def log(s):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(s + "\n")
    print(s, flush=True)

CONFIG = dict(host="192.168.111.141", port=3306, user="root", password="root",
              database="smart_health", charset="utf8mb4", connect_timeout=600)
# 与 fact 表完全一致的全部业务列（不含自增主键 fact_id）。
# 必须让 SELECT 的每一列都出现在 GROUP BY 中，否则 only_full_group_by 报 1055。
COLS = ["facility_id","diagnosis_id","procedure_id","drg_id","age_group","zip3","gender",
        "race","ethnicity","length_of_stay","type_of_admission","patient_disposition",
        "discharge_year","apr_severity_code","apr_severity_desc","apr_risk_mortality",
        "apr_medical_surgical","payment_typology_1","payment_typology_2","payment_typology_3",
        "birth_weight","ed_indicator","total_charges","total_costs"]
COLS_CSV = ", ".join(COLS)
GROUP_BY = ", ".join(COLS)  # 2022 内 discharge_year 恒定、apr_severity_desc 由 code 决定，全列 GROUP BY 等价于按业务键去重

t0 = time.time()
log("[start] %s" % time.strftime("%H:%M:%S"))
conn = pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **CONFIG)
conn.autocommit(False)
try:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS n FROM fact_inpatient_discharge WHERE discharge_year=2022")
    before = cur.fetchone()["n"]
    log("before_2022=%d" % before)

    log("creating clean table ...")
    cur.execute("DROP TABLE IF EXISTS fact_inpatient_discharge_clean")
    cur.execute("CREATE TABLE fact_inpatient_discharge_clean LIKE fact_inpatient_discharge")

    log("inserting 2021 ...")
    cur.execute("INSERT INTO fact_inpatient_discharge_clean SELECT * FROM fact_inpatient_discharge WHERE discharge_year=2021")
    cur.execute("SELECT COUNT(*) AS n FROM fact_inpatient_discharge_clean")
    n21 = cur.fetchone()["n"]
    log("after_2021=%d" % n21)

    log("inserting deduped 2022 (GROUP BY %d cols, only_full_group_by safe) ..." % len(COLS))
    cur.execute(("INSERT INTO fact_inpatient_discharge_clean (" + COLS_CSV + ") "
                 "SELECT " + COLS_CSV + " FROM fact_inpatient_discharge "
                 "WHERE discharge_year=2022 GROUP BY " + GROUP_BY))
    cur.execute("SELECT COUNT(*) AS n FROM fact_inpatient_discharge_clean WHERE discharge_year=2022")
    n22 = cur.fetchone()["n"]
    log("after_dedup_2022=%d" % n22)

    cur.execute("SELECT COUNT(*) AS n FROM fact_inpatient_discharge_clean")
    clean = cur.fetchone()["n"]
    log("clean_total=%d (expected ~%d)" % (clean, n21 + n22))

    if n22 < before:  # 去重确实删掉了重复
        log("renaming tables (atomic swap) ...")
        cur.execute(("RENAME TABLE fact_inpatient_discharge TO fact_inpatient_discharge_old, "
                     "fact_inpatient_discharge_clean TO fact_inpatient_discharge"))
        conn.commit()
        log("[OK] committed. old table kept as fact_inpatient_discharge_old (drop manually if sure).")
    else:
        conn.rollback()
        log("[WARN] dedup removed 0 rows, rolled back (nothing to do).")
except Exception as e:
    conn.rollback()
    log("[ERROR] rolled back: %r" % e)
finally:
    conn.close()
log("[done] elapsed %.1fs" % (time.time() - t0))
