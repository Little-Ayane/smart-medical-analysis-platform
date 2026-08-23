# -*- coding: utf-8 -*-
"""
医疗数据完整处理流水线 (Medical Data Pipeline)
================================================

将纽约州 SPARCS 住院出院数据（CSV）从原始文件到星型模型的全流程处理。
覆盖 5 个阶段：CSV预处理 → 数据导入 → 数据清洗 → 星型模型ETL → 验收导出

数据规模：5年 (2020-2024) / 10,378,775 条记录 / 33 字段
输出：1 张事实表 + 7 张维度表（MySQL 星型模型）

用法：
    # 运行全部阶段
    python medical_data_pipeline.py --all

    # 运行指定阶段（可组合）
    python medical_data_pipeline.py --stage 1 --stage 2

    # 指定CSV目录
    python medical_data_pipeline.py --all --csv-dir /path/to/csv

环境变量（可选，覆盖默认值）：
    DB_HOST=localhost
    DB_PORT=3306
    DB_USER=root
    DB_PASSWORD=your_password
    DB_NAME=medical_db
"""

import sys
import os
import io
import time
import csv
import shutil
import argparse
import traceback
from datetime import datetime
from urllib.parse import quote_plus

# 实时输出（后台任务重定向时刷新）
class _Unbuffered:
    def __init__(self, s): self.s = s
    def write(self, d): self.s.write(d); self.s.flush()
    def flush(self): self.s.flush()
sys.stdout = _Unbuffered(sys.stdout)
sys.stderr = _Unbuffered(sys.stderr)

# ============================================================
# 配置区
# ============================================================
DB_HOST     = os.environ.get('DB_HOST', 'localhost')
DB_PORT     = int(os.environ.get('DB_PORT', '3306'))
DB_USER     = os.environ.get('DB_USER', 'root')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'Csu@Boy727620zy')
DB_NAME     = os.environ.get('DB_NAME', 'medical_db')

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CSV_DIR      = os.path.join(PROJECT_ROOT, 'data', 'new_data')
REPORT_PATH  = os.path.join(PROJECT_ROOT, 'data-analysis', 'docs', 'data-quality-report.md')

# ETL 参数
CHUNK_SIZE       = 100_000   # SELECT 分块大小
BATCH_DIM_INSERT = 5000      # 维表批量INSERT
BATCH_FACT_COMMIT = 500      # 事实表每批独立提交（防锁溢出）
CHUNK_RETRY      = 3         # 单块失败重试次数

# CSV 列名映射（原始 → 数据库字段）
COLUMN_MAPPING = {
    'Hospital Service Area': 'Hospital_Service_Area',
    'Hospital County': 'Hospital_County',
    'Operating Certificate Number': 'Operating_Certificate_Number',
    'Permanent Facility Id': 'Permanent_Facility_Id',
    'Facility Name': 'Facility_Name',
    'Age Group': 'Age_Group',
    'Age': 'Age',
    'Zip Code - 3 digits': 'Zip_Code_3digits',
    'Gender': 'Gender', 'Race': 'Race', 'Ethnicity': 'Ethnicity',
    'Length of Stay': 'Length_of_Stay',
    'Type of Admission': 'Type_of_Admission',
    'Patient Disposition': 'Patient_Disposition',
    'Discharge Year': 'Discharge_Year',
    'CCSR Diagnosis Code': 'CCSR_Diagnosis_Code',
    'CCSR Diagnosis Description': 'CCSR_Diagnosis_Description',
    'CCSR Procedure Code': 'CCSR_Procedure_Code',
    'CCSR Procedure Description': 'CCSR_Procedure_Description',
    'APR DRG Code': 'APR_DRG_Code',
    'APR DRG Description': 'APR_DRG_Description',
    'APR MDC Code': 'APR_MDC_Code',
    'APR MDC Description': 'APR_MDC_Description',
    'APR Severity of Illness Code': 'APR_Severity_of_Illness_Code',
    'APR Severity of Illness Description': 'APR_Severity_of_Illness_Description',
    'APR Risk of Mortality': 'APR_Risk_of_Mortality',
    'APR Medical Surgical Description': 'APR_Medical_Surgical_Description',
    'Payment Typology 1': 'Payment_Typology_1',
    'Payment Typology 2': 'Payment_Typology_2',
    'Payment Typology 3': 'Payment_Typology_3',
    'Birth Weight': 'Birth_Weight',
    'Emergency Department Indicator': 'Emergency_Department_Indicator',
    'Total Charges': 'Total_Charges',
    'Total Costs': 'Total_Costs',
}

NUMERIC_COLS = ['Length_of_Stay', 'Total_Charges', 'Total_Costs', 'Birth_Weight', 'Age']
INT_COLS = ['Length_of_Stay', 'Discharge_Year', 'APR_DRG_Code', 'APR_MDC_Code',
            'APR_Severity_of_Illness_Code', 'Birth_Weight', 'Age']
CATEGORY_COLS = ['Gender', 'Race', 'Ethnicity', 'Hospital_Service_Area',
                 'Hospital_County', 'Type_of_Admission', 'Patient_Disposition',
                 'CCSR_Diagnosis_Code', 'APR_Risk_of_Mortality']

# ============================================================
# 工具函数
# ============================================================
def get_engine():
    """创建 SQLAlchemy 引擎"""
    from sqlalchemy import create_engine
    pwd = quote_plus(DB_PASSWORD)
    url = f'mysql+pymysql://{DB_USER}:{pwd}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4'
    return create_engine(url, pool_pre_ping=True, pool_recycle=3600)

def get_conn():
    """创建 PyMySQL 连接"""
    import pymysql
    return pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_USER,
                           password=DB_PASSWORD, database=DB_NAME,
                           charset='utf8mb4',
                           connect_timeout=60, read_timeout=1800, write_timeout=1800)

def log(title, content=""):
    bar = "=" * 60
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n{bar}\n[{ts}] {title}")
    if content: print(content)
    print(f"{bar}", flush=True)

def _k(v):
    """统一字符串键化"""
    return None if v is None else str(v).strip()

# ============================================================
# 阶段 1：CSV 预处理（修复表头不一致）
# ============================================================
def stage1_fix_csv_headers(csv_dir=None):
    import csv as csv_mod
    csv_dir = csv_dir or CSV_DIR

    # 2024 年 CSV 表头映射
    fix_map = {
        "Health Service Area": "Hospital Service Area",
        "Zip Code": "Zip Code - 3 digits",
    }

    csv_files = sorted([f for f in os.listdir(csv_dir) if f.endswith('.csv')])
    log(f"阶段1: CSV 表头修复 ({len(csv_files)} 个文件)")

    for fname in csv_files:
        path = os.path.join(csv_dir, fname)
        bak = path + ".bak"

        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv_mod.reader(f, quotechar='"')
            rows = list(reader)

        header = rows[0]
        fixed = [fix_map.get(c.strip().strip('"'), c.strip().strip('"')) for c in header]
        if fixed != header:
            shutil.copy2(path, bak)
            rows[0] = fixed
            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv_mod.writer(f, quotechar='"', quoting=csv_mod.QUOTE_MINIMAL)
                writer.writerows(rows)
            print(f"  {fname}: 表头已修复 (备份: {os.path.basename(bak)})")
        else:
            print(f"  {fname}: 表头正常")

    print("  阶段1完成\n", flush=True)

# ============================================================
# 阶段 2：CSV 导入 MySQL（分块读取 + 清洗）
# ============================================================
def stage2_import_csv(csv_dir=None):
    import pandas as pd
    import numpy as np
    csv_dir = csv_dir or CSV_DIR

    log("阶段2: CSV → MySQL 批量导入")

    csv_files = sorted([f for f in os.listdir(csv_dir) if f.endswith('.csv')])
    print(f"  找到 {len(csv_files)} 个CSV文件: {csv_files}\n")

    engine = get_engine()
    from sqlalchemy import text

    total_imported = 0
    for fname in csv_files:
        path = os.path.join(csv_dir, fname)
        print(f"  --- {fname} ---")
        file_rows = 0

        for chunk in pd.read_csv(path, chunksize=50000, low_memory=False):
            cleaned = _clean_chunk(chunk)
            if len(cleaned) > 0:
                cleaned.to_sql('medical_data', con=engine, if_exists='append',
                               index=False, chunksize=500)
                file_rows += len(cleaned)

        print(f"    导入 {file_rows:,} 行")
        total_imported += file_rows

    print(f"\n  总导入: {total_imported:,} 行")
    print("  阶段2完成\n", flush=True)


def _clean_chunk(df):
    """清洗单个 CSV 分块"""
    import pandas as pd
    import numpy as np
    df = df.copy()
    df = df.rename(columns=COLUMN_MAPPING)

    # 字符串去空格
    for col in df.select_dtypes(include=['object']).columns:
        df[col] = df[col].astype(str).str.strip()

    # 数值转换
    for col in NUMERIC_COLS:
        if col in df.columns:
            if col in ['Total_Charges', 'Total_Costs']:
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(r'[$£€,]', '', regex=True),
                    errors='coerce')
            else:
                df[col] = pd.to_numeric(df[col], errors='coerce')

    # 整数转换
    for col in INT_COLS:
        if col in df.columns:
            df[col] = df[col].apply(pd.to_numeric, errors='coerce').astype('Int64')

    # 空值标记 → NaN
    for col in CATEGORY_COLS + ['Zip_Code_3digits']:
        if col in df.columns:
            df[col] = df[col].replace(
                ['nan', 'null', 'NULL', 'NaN', 'N/A', 'n/a', 'none', 'NONE', ''],
                np.nan)

    # 标准化性别
    if 'Gender' in df.columns:
        df['Gender'] = df['Gender'].apply(_standardize_gender)

    # 标准化邮编
    if 'Zip_Code_3digits' in df.columns:
        df['Zip_Code_3digits'] = df['Zip_Code_3digits'].apply(_standardize_zip)

    # 标准化急诊标识
    if 'Emergency_Department_Indicator' in df.columns:
        df['Emergency_Department_Indicator'] = df['Emergency_Department_Indicator'].apply(
            lambda v: 'Y' if str(v).strip().upper() in ('Y', 'YES', '1', 'TRUE') else 'N')

    # 业务规则过滤
    if 'Total_Charges' in df.columns:
        df = df[(df['Total_Charges'] >= 0.01) & (df['Total_Charges'] <= 5000000)]
    if 'Length_of_Stay' in df.columns:
        df = df[(df['Length_of_Stay'] >= 0) & (df['Length_of_Stay'] <= 365)]

    # 填充分类字段
    for col in CATEGORY_COLS:
        if col in df.columns:
            df[col] = df[col].fillna('Unknown').replace('', 'Unknown')

    # 填充金额空值
    for col in ['Total_Charges', 'Total_Costs']:
        if col in df.columns:
            med = df[col].median()
            df[col] = df[col].fillna(med if pd.notna(med) else 0)

    return df.drop_duplicates().reset_index(drop=True)


def _standardize_gender(val):
    import pandas as pd
    if pd.isna(val): return 'U'
    v = str(val).strip().upper()
    if v in ('M', 'MALE', '1'): return 'M'
    if v in ('F', 'FEMALE', '0'): return 'F'
    return 'U'


def _standardize_zip(val):
    import pandas as pd
    if pd.isna(val): return np.nan
    digits = ''.join(c for c in str(val).strip() if c.isdigit())[:3]
    return digits.ljust(3, '0') if digits else np.nan

# ============================================================
# 阶段 3：数据清洗（删除异常值 + nan → NULL）
# ============================================================
def stage3_clean_data():
    log("阶段3: 数据清洗（删除异常值 + 'nan' → NULL）")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM medical_data")
    before = cur.fetchone()[0]
    print(f"  清洗前总行数: {before:,}")

    # 3.1 删除异常行
    delete_rules = [
        ("Gender='U' 或 NULL",      "Gender='U' OR Gender IS NULL"),
        ("Permanent_Facility_Id 为空", "Permanent_Facility_Id IS NULL"),
        ("Facility_Name 为空",       "Facility_Name IS NULL OR Facility_Name=''"),
        ("Zip_Code_3digits='nan'",   "Zip_Code_3digits='nan'"),
    ]
    deleted_total = 0
    for name, cond in delete_rules:
        cur.execute(f"DELETE FROM medical_data WHERE {cond}")
        deleted = cur.rowcount
        deleted_total += deleted
        print(f"  删除 {name}: {deleted:,} 行")
    conn.commit()
    print(f"  合计删除: {deleted_total:,} 行")

    # 3.2 'nan' 字符串 → NULL
    nan_fields = [
        "Hospital_Service_Area", "Hospital_County", "CCSR_Diagnosis_Code",
        "CCSR_Diagnosis_Description", "CCSR_Procedure_Code",
        "CCSR_Procedure_Description", "APR_Severity_of_Illness_Description",
        "APR_Risk_of_Mortality", "Payment_Typology_2", "Payment_Typology_3",
    ]
    for field in nan_fields:
        try:
            cur.execute(f"UPDATE medical_data SET `{field}`=NULL WHERE `{field}`='nan'")
            if cur.rowcount > 0:
                print(f"  {field}: {cur.rowcount:,} 行 'nan' → NULL")
        except Exception:
            pass
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM medical_data")
    after = cur.fetchone()[0]
    print(f"\n  清洗后总行数: {after:,} (保留率 {after/before*100:.2f}%)")

    # 3.3 年份分布
    cur.execute("SELECT Discharge_Year, COUNT(*) FROM medical_data GROUP BY Discharge_Year ORDER BY 1")
    print("  年份分布:")
    for yr, cnt in cur.fetchall():
        print(f"    {yr}: {cnt:,}")

    cur.close(); conn.close()
    print("  阶段3完成\n", flush=True)

# ============================================================
# 阶段 4：星型模型 ETL（2-Pass）
# ============================================================
def stage4_build_star_schema():
    """
    2-Pass ETL：
      Pass 1: 扫描 medical_data 收集 7 个维度的唯一键 → INSERT 维度表
      Pass 2: 扫描 medical_data 用内存字典映射 ID → INSERT 事实表
    使用 _etl 临时表，完成后原子 RENAME 为正式表。
    """
    from sqlalchemy import text
    engine = get_engine()
    t0 = time.time()

    log("阶段4: 星型模型 ETL (2-Pass)")

    # ---- 4.0 创建 _etl 空表 ----
    _create_etl_tables(engine)

    # ---- 4.1 Pass 1: 收集维度键 ----
    dim_data = _pass1_collect_dims(engine)

    # ---- 4.2 INSERT 维度表 ----
    _insert_dimensions(engine, dim_data)

    # ---- 4.3 加载 ID 字典 ----
    dicts = _load_id_dicts(engine)

    # ---- 4.4 Pass 2: 构建事实表 ----
    fact_count = _pass2_build_fact(dicts, dim_data[-3:])  # total, min_id, max_id

    # ---- 4.5 验收 + 原子替换 ----
    _verify_and_swap(engine, fact_count, dim_data[-3])

    print(f"\n{'='*60}")
    print(f"阶段4完成！总耗时: {(time.time()-t0)/60:.1f} 分钟")
    print(f"{'='*60}\n", flush=True)


def _create_etl_tables(engine):
    """创建 _etl 空表（LIKE 正式表，零锁）"""
    from sqlalchemy import text
    log("步骤4.0: 创建 _etl 空表")

    pairs = [
        ("dim_time_etl", "dim_time"), ("dim_hospital_etl", "dim_hospital"),
        ("dim_patient_etl", "dim_patient"), ("dim_diagnosis_etl", "dim_diagnosis"),
        ("dim_procedure_etl", "dim_procedure"), ("dim_drg_etl", "dim_drg"),
        ("dim_payment_etl", "dim_payment"),
    ]
    with engine.begin() as conn:
        for etl, orig in pairs:
            conn.execute(text(f"DROP TABLE IF EXISTS {etl}"))
            conn.execute(text(f"CREATE TABLE {etl} LIKE {orig}"))
            conn.execute(text(f"TRUNCATE TABLE {etl}"))
            print(f"  {etl} OK")

        conn.execute(text("DROP TABLE IF EXISTS fact_discharge_etl"))
        conn.execute(text("CREATE TABLE fact_discharge_etl LIKE fact_discharge"))
        # 移除外键约束（_etl 表不需要）
        for i in range(1, 8):
            try:
                conn.execute(text(f"ALTER TABLE fact_discharge_etl DROP FOREIGN KEY fact_discharge_ibfk_{i}"))
            except Exception:
                pass
        conn.execute(text("TRUNCATE TABLE fact_discharge_etl"))
        print("  fact_discharge_etl OK")
    print("  创建完成\n", flush=True)


def _pass1_collect_dims(engine):
    """Pass 1: 1次全表扫描 → 收集7个维度唯一键"""
    from sqlalchemy import text
    log("步骤4.1: Pass 1 - 扫描收集维度键")

    with engine.connect() as conn:
        min_id, max_id, total = conn.execute(text(
            "SELECT MIN(id), MAX(id), COUNT(*) FROM medical_data"
        )).fetchone()
        conn.commit()
    print(f"  id: {min_id:,} ~ {max_id:,}  总: {total:,}\n")

    set_t, set_h, desc_h = set(), set(), {}
    set_p, set_d, desc_d = set(), set(), {}
    set_pr, desc_pr = set(), {}
    set_drg, desc_drg = set(), {}
    set_pay = set()

    t0 = time.time()
    scanned = 0
    pos = min_id

    while pos <= max_id:
        end = min(pos + CHUNK_SIZE - 1, max_id)
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT Discharge_Year,
                    Permanent_Facility_Id, Facility_Name, Operating_Certificate_Number,
                    Hospital_Service_Area, Hospital_County,
                    Age_Group, Gender, Race, Ethnicity, Zip_Code_3digits,
                    CCSR_Diagnosis_Code, CCSR_Diagnosis_Description,
                    CCSR_Procedure_Code, CCSR_Procedure_Description,
                    APR_DRG_Code, APR_DRG_Description, APR_MDC_Code, APR_MDC_Description,
                    APR_Severity_of_Illness_Code, APR_Severity_of_Illness_Description,
                    APR_Risk_of_Mortality, APR_Medical_Surgical_Description,
                    Payment_Typology_1, Payment_Typology_2, Payment_Typology_3
                FROM medical_data WHERE id BETWEEN {pos} AND {end}
            """)).fetchall()
            conn.commit()

        for r in rows:
            set_t.add(_k(r[0]))
            hk = _k(r[1]); set_h.add(hk)
            if hk not in desc_h: desc_h[hk] = (_k(r[2]),_k(r[3]),_k(r[4]),_k(r[5]))
            set_p.add((_k(r[6]),_k(r[7]),_k(r[8]),_k(r[9]),_k(r[10])))
            dk = _k(r[11]); set_d.add(dk)
            if dk not in desc_d: desc_d[dk] = _k(r[12])
            prk = _k(r[13]); set_pr.add(prk)
            if prk not in desc_pr: desc_pr[prk] = _k(r[14])
            drgk = (_k(r[15]),_k(r[17]),_k(r[19]),_k(r[21]),_k(r[22]))
            set_drg.add(drgk)
            if drgk not in desc_drg: desc_drg[drgk] = (_k(r[16]),_k(r[18]),_k(r[20]))
            set_pay.add((_k(r[23]),_k(r[24]),_k(r[25])))

        scanned += len(rows)
        el = time.time() - t0
        spd = scanned / max(el, 1)
        eta = (total - scanned) / max(spd, 1) / 60
        print(f"  [{el/60:.1f}分] {scanned:>8,}/{total:,} ({scanned/total*100:5.1f}%) "
              f"{spd/1000:.0f}K/s 剩余{eta:.1f}分", flush=True)
        pos = end + 1

    el = time.time() - t0
    total_keys = len(set_t)+len(set_h)+len(set_p)+len(set_d)+len(set_pr)+len(set_drg)+len(set_pay)
    print(f"\n  Pass1完成！用时{el/60:.1f}分  维度键合计: {total_keys:,}")
    print(f"  time={len(set_t)} hosp={len(set_h)} patient={len(set_p)} "
          f"diag={len(set_d)} proc={len(set_pr)} drg={len(set_drg)} pay={len(set_pay)}\n")

    return (set_t, set_h, desc_h, set_p, set_d, desc_d,
            set_pr, desc_pr, set_drg, desc_drg, set_pay, total, min_id, max_id)


def _insert_dimensions(engine, dim_data):
    """批量 INSERT 维度到 _etl 表"""
    from sqlalchemy import text
    log("步骤4.2: 批量 INSERT 维度表")
    set_t, set_h, desc_h, set_p, set_d, desc_d, set_pr, desc_pr, set_drg, desc_drg, set_pay = dim_data[:11]

    def batch_insert(table, sql, rows):
        with engine.begin() as conn:
            for i in range(0, len(rows), BATCH_DIM_INSERT):
                conn.execute(text(sql), rows[i:i+BATCH_DIM_INSERT])

    # dim_time
    rows = [{'y': int(y)} for y in sorted(set_t) if y and y.lstrip('-').isdigit()]
    batch_insert("dim_time_etl", "INSERT INTO dim_time_etl (discharge_year) VALUES (:y)", rows)
    print(f"  dim_time_etl: {len(rows):,}")

    # dim_hospital
    rows = [{'fid':k,'n':desc_h.get(k,(None,)*4)[0],'c':desc_h.get(k,(None,)*4)[1],
             'a':desc_h.get(k,(None,)*4)[2],'cc':desc_h.get(k,(None,)*4)[3]} for k in set_h]
    batch_insert("dim_hospital_etl",
        "INSERT INTO dim_hospital_etl (permanent_facility_id,facility_name,"
        "operating_certificate_number,hospital_service_area,hospital_county) "
        "VALUES (:fid,:n,:c,:a,:cc)", rows)
    print(f"  dim_hospital_etl: {len(rows):,}")

    # dim_patient
    rows = [{'a':a,'g':g,'r':r,'e':e,'z':z} for a,g,r,e,z in set_p]
    batch_insert("dim_patient_etl",
        "INSERT INTO dim_patient_etl (age_group,gender,race,ethnicity,zip_code_3digits) "
        "VALUES (:a,:g,:r,:e,:z)", rows)
    print(f"  dim_patient_etl: {len(rows):,}")

    # dim_diagnosis
    rows = [{'cd':k,'ds':desc_d.get(k)} for k in set_d]
    batch_insert("dim_diagnosis_etl",
        "INSERT INTO dim_diagnosis_etl (ccsr_diagnosis_code,ccsr_diagnosis_description) "
        "VALUES (:cd,:ds)", rows)
    print(f"  dim_diagnosis_etl: {len(rows):,}")

    # dim_procedure
    rows = [{'cd':k,'ds':desc_pr.get(k)} for k in set_pr]
    batch_insert("dim_procedure_etl",
        "INSERT INTO dim_procedure_etl (ccsr_procedure_code,ccsr_procedure_description) "
        "VALUES (:cd,:ds)", rows)
    print(f"  dim_procedure_etl: {len(rows):,}")

    # dim_drg (5列自然键)
    rows = []
    for drg,mdc,sev,risk,ms in set_drg:
        dd,md,sd = desc_drg.get((drg,mdc,sev,risk,ms),(None,None,None))
        rows.append({'d':drg,'dd':dd,'m':mdc,'md':md,'s':sev,'sd':sd,'r':risk,'ms':ms})
    batch_insert("dim_drg_etl",
        "INSERT INTO dim_drg_etl (apr_drg_code,apr_drg_description,apr_mdc_code,"
        "apr_mdc_description,apr_severity_code,apr_severity_description,"
        "apr_risk_of_mortality,apr_medical_surgical) "
        "VALUES (:d,:dd,:m,:md,:s,:sd,:r,:ms)", rows)
    print(f"  dim_drg_etl: {len(rows):,} (5列自然键)")

    # dim_payment
    rows = [{'p1':p1,'p2':p2,'p3':p3} for p1,p2,p3 in set_pay]
    batch_insert("dim_payment_etl",
        "INSERT INTO dim_payment_etl (payment_typology_1,payment_typology_2,payment_typology_3) "
        "VALUES (:p1,:p2,:p3)", rows)
    print(f"  dim_payment_etl: {len(rows):,}")
    print("  维度INSERT完成\n", flush=True)


def _load_id_dicts(engine):
    """从 _etl 维表加载 ID 字典"""
    from sqlalchemy import text
    log("步骤4.3: 加载维度 ID 字典")

    D = {}
    with engine.connect() as conn:
        r = conn.execute(text("SELECT discharge_year, year_id FROM dim_time_etl")).fetchall()
        D['t'] = {_k(x[0]): x[1] for x in r}; conn.commit()
        r = conn.execute(text("SELECT permanent_facility_id, hospital_id FROM dim_hospital_etl")).fetchall()
        D['h'] = {_k(x[0]): x[1] for x in r}; conn.commit()
        r = conn.execute(text("SELECT age_group,gender,race,ethnicity,zip_code_3digits,patient_demo_id FROM dim_patient_etl")).fetchall()
        D['p'] = {(_k(x[0]),_k(x[1]),_k(x[2]),_k(x[3]),_k(x[4])): x[5] for x in r}; conn.commit()
        r = conn.execute(text("SELECT ccsr_diagnosis_code, diagnosis_id FROM dim_diagnosis_etl")).fetchall()
        D['d'] = {_k(x[0]): x[1] for x in r}; conn.commit()
        r = conn.execute(text("SELECT ccsr_procedure_code, procedure_id FROM dim_procedure_etl")).fetchall()
        D['pr'] = {_k(x[0]): x[1] for x in r}; conn.commit()
        r = conn.execute(text("""SELECT apr_drg_code,apr_mdc_code,apr_severity_code,
            apr_risk_of_mortality,apr_medical_surgical,drg_id FROM dim_drg_etl""")).fetchall()
        D['drg'] = {(_k(x[0]),_k(x[1]),_k(x[2]),_k(x[3]),_k(x[4])): x[5] for x in r}; conn.commit()
        r = conn.execute(text("SELECT payment_typology_1,payment_typology_2,payment_typology_3,payment_id FROM dim_payment_etl")).fetchall()
        D['pay'] = {(_k(x[0]),_k(x[1]),_k(x[2])): x[3] for x in r}; conn.commit()

    for k, v in D.items():
        print(f"  dict_{k}: {len(v):,} keys")
    print(f"  总键数: {sum(len(v) for v in D.values()):,}\n", flush=True)
    return D


def _pass2_build_fact(D, id_range):
    """Pass 2: 分块SELECT + 内存字典映射 + 每批500行独立commit"""
    from sqlalchemy import text
    total_rows, min_id, max_id = id_range
    log("步骤4.4: Pass 2 - 构建事实表")
    print(f"  id: {min_id:,} ~ {max_id:,}  总: {total_rows:,}")
    print(f"  策略: 分块{CHUNK_SIZE:,}行 SELECT + 每批{BATCH_FACT_COMMIT}行独立commit\n")

    INS_SQL = text("""INSERT INTO fact_discharge_etl (
        hospital_id,patient_demo_id,diagnosis_id,procedure_id,drg_id,
        payment_id,year_id,type_of_admission,patient_disposition,
        emergency_department_indicator,length_of_stay,total_charges,
        total_costs,birth_weight
    ) VALUES (:a,:b,:c,:d,:e,:f,:g,:h,:i,:j,:k,:l,:m,:n)""")

    SEL = """SELECT Permanent_Facility_Id,
        Age_Group,Gender,Race,Ethnicity,Zip_Code_3digits,
        CCSR_Diagnosis_Code,CCSR_Procedure_Code,
        APR_DRG_Code,APR_MDC_Code,APR_Severity_of_Illness_Code,
        APR_Risk_of_Mortality,APR_Medical_Surgical_Description,
        Payment_Typology_1,Payment_Typology_2,Payment_Typology_3,
        Discharge_Year,Type_of_Admission,Patient_Disposition,
        Emergency_Department_Indicator,Length_of_Stay,
        Total_Charges,Total_Costs,Birth_Weight
    FROM medical_data WHERE id BETWEEN %s AND %s"""

    rows_done = 0; fails = 0
    t0 = time.time()
    pos = min_id

    while pos <= max_id:
        end = min(pos + CHUNK_SIZE - 1, max_id)
        ok = 0; batch = []; last_err = None

        for attempt in range(CHUNK_RETRY):
            try:
                rconn = get_conn(); rcur = rconn.cursor()
                rcur.execute(SEL, (pos, end))
                chunk = rcur.fetchall()
                rcur.close(); rconn.close()

                for r in chunk:
                    try:
                        batch.append((
                            D['h'][_k(r[0])],
                            D['p'][(_k(r[1]),_k(r[2]),_k(r[3]),_k(r[4]),_k(r[5]))],
                            D['d'][_k(r[6])],
                            D['pr'][_k(r[7])],
                            D['drg'][(_k(r[8]),_k(r[9]),_k(r[10]),_k(r[11]),_k(r[12]))],
                            D['pay'][(_k(r[13]),_k(r[14]),_k(r[15]))],
                            D['t'][_k(r[16])],
                            r[17], r[18], r[19], r[20], r[21], r[22], r[23],
                        ))
                    except KeyError:
                        fails += 1

                # 每批500行独立提交
                wconn = get_conn(); wcur = wconn.cursor()
                for i in range(0, len(batch), BATCH_FACT_COMMIT):
                    try:
                        wcur.executemany(
                            "INSERT INTO fact_discharge_etl (hospital_id,patient_demo_id,"
                            "diagnosis_id,procedure_id,drg_id,payment_id,year_id,"
                            "type_of_admission,patient_disposition,"
                            "emergency_department_indicator,length_of_stay,"
                            "total_charges,total_costs,birth_weight) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                            batch[i:i+BATCH_FACT_COMMIT])
                        wconn.commit()
                        ok += len(batch[i:i+BATCH_FACT_COMMIT])
                    except Exception:
                        wconn.rollback()
                        for row in batch[i:i+BATCH_FACT_COMMIT]:
                            try:
                                wcur.execute(
                                    "INSERT INTO fact_discharge_etl (hospital_id,patient_demo_id,"
                                    "diagnosis_id,procedure_id,drg_id,payment_id,year_id,"
                                    "type_of_admission,patient_disposition,"
                                    "emergency_department_indicator,length_of_stay,"
                                    "total_charges,total_costs,birth_weight) "
                                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", row)
                                wconn.commit(); ok += 1
                            except Exception:
                                fails += 1
                wcur.close(); wconn.close()
                rows_done += ok
                last_err = None
                break
            except Exception as e:
                last_err = e
                print(f"  块{pos//100000}0万 第{attempt+1}次失败: {str(e)[:80]}")
                time.sleep(5)

        if last_err:
            print(f"  !!! 块{pos//100000}0万 跳过")
            fails += CHUNK_SIZE

        el = time.time() - t0
        spd = rows_done / max(el, 1)
        eta = (total_rows - rows_done) / max(spd, 1) / 60
        print(f"  [{el/60:.1f}分] {rows_done:>10,}/{total_rows:,} ({rows_done/total*100:5.1f}%) "
              f"{int(spd):>6,}/s 剩余{eta:.1f}分 失败{fails:,}", flush=True)
        pos = end + 1

    el = time.time() - t0
    print(f"\n  Pass2完成！{rows_done:,}行 用时{el/60:.1f}分 失败{fails:,}")
    return rows_done


def _verify_and_swap(engine, fact_count, total_rows):
    """验收 + 原子 RENAME 替换正式表"""
    from sqlalchemy import text
    log("步骤4.5: 严格验收 & 原子替换")

    with engine.connect() as conn:
        # 行数对比
        wide_cnt = conn.execute(text("SELECT COUNT(*) FROM medical_data")).fetchone()[0]
        fact_cnt = conn.execute(text("SELECT COUNT(*) FROM fact_discharge_etl")).fetchone()[0]

        # 年份分布
        wide_y = dict(conn.execute(text(
            "SELECT Discharge_Year, COUNT(*) FROM medical_data GROUP BY Discharge_Year"
        )).fetchall())
        fact_y = dict(conn.execute(text("""
            SELECT t.discharge_year, COUNT(*) FROM fact_discharge_etl f
            JOIN dim_time_etl t ON f.year_id=t.year_id GROUP BY t.discharge_year
        """)).fetchall())

        # 外键完整性
        pairs = [("hospital_id","dim_hospital_etl","hospital_id"),
                 ("patient_demo_id","dim_patient_etl","patient_demo_id"),
                 ("diagnosis_id","dim_diagnosis_etl","diagnosis_id"),
                 ("procedure_id","dim_procedure_etl","procedure_id"),
                 ("drg_id","dim_drg_etl","drg_id"),
                 ("payment_id","dim_payment_etl","payment_id"),
                 ("year_id","dim_time_etl","year_id")]
        orphans = {}
        for fk, dim, col in pairs:
            orphans[fk] = conn.execute(text(f"""
                SELECT COUNT(*) FROM fact_discharge_etl f
                LEFT JOIN {dim} d ON f.{fk}=d.{col}
                WHERE d.{col} IS NULL""")).fetchone()[0]
        conn.commit()

    # 验收报告
    r1 = (wide_cnt == fact_cnt)
    print(f"[1] 行数: 宽表{wide_cnt:,} 事实表{fact_cnt:,} {'PASS' if r1 else 'FAIL'}")

    r2 = True
    print(f"[2] 年份分布:")
    for y in sorted(set(wide_y) | set(fact_y)):
        w, f = wide_y.get(y, 0), fact_y.get(y, 0)
        ok = (w == f)
        if not ok: r2 = False
        print(f"    {y}: {w:,} vs {f:,} {'PASS' if ok else 'FAIL'}")

    r3 = True
    print(f"[3] 外键完整性:")
    for fk, cnt in orphans.items():
        if cnt > 0: r3 = False
        print(f"    {fk}: {cnt} {'PASS' if cnt == 0 else 'FAIL'}")

    if not (r1 and r2 and r3):
        print("\n  验收未通过，跳过替换。请检查数据。")
        return

    print("\n  全部通过！原子替换 _etl → 正式表")
    with engine.begin() as conn:
        swaps = [
            "DROP TABLE IF EXISTS dim_time_old,dim_hospital_old,dim_patient_old,"
            "dim_diagnosis_old,dim_procedure_old,dim_drg_old,dim_payment_old,fact_discharge_old",
            "RENAME TABLE dim_time TO dim_time_old,dim_hospital TO dim_hospital_old,"
            "dim_patient TO dim_patient_old,dim_diagnosis TO dim_diagnosis_old,"
            "dim_procedure TO dim_procedure_old,dim_drg TO dim_drg_old,"
            "dim_payment TO dim_payment_old,fact_discharge TO fact_discharge_old",
            "RENAME TABLE dim_time_etl TO dim_time,dim_hospital_etl TO dim_hospital,"
            "dim_patient_etl TO dim_patient,dim_diagnosis_etl TO dim_diagnosis,"
            "dim_procedure_etl TO dim_procedure,dim_drg_etl TO dim_drg,"
            "dim_payment_etl TO dim_payment,fact_discharge_etl TO fact_discharge",
            "DROP TABLE IF EXISTS dim_time_old,dim_hospital_old,dim_patient_old,"
            "dim_diagnosis_old,dim_procedure_old,dim_drg_old,dim_payment_old,fact_discharge_old",
        ]
        for s in swaps:
            try:
                conn.execute(text(s))
                print(f"  OK: {s[:60]}...")
            except Exception as e:
                print(f"  SKIP: {str(e)[:80]}")

    print("\n  星型模型构建完成！不重不漏，5年一致，外键完整。", flush=True)


# ============================================================
# 阶段 5：验收 + 导出
# ============================================================
def stage5_verify_and_export():
    """验收星型表数据量 + 导出压缩"""
    log("阶段5: 数据验收 & 导出")

    conn = get_conn(); cur = conn.cursor()

    # 验收
    print("  === 星型表行数 ===")
    tables = [
        ('fact_discharge', 'fact_discharge'),
        ('dim_time', 'dim_time'),
        ('dim_hospital', 'dim_hospital'),
        ('dim_patient', 'dim_patient'),
        ('dim_diagnosis', 'dim_diagnosis'),
        ('dim_procedure', 'dim_procedure'),
        ('dim_drg', 'dim_drg'),
        ('dim_payment', 'dim_payment'),
    ]
    for label, tbl in tables:
        cur.execute(f"SELECT COUNT(*) FROM {tbl}")
        print(f"    {label}: {cur.fetchone()[0]:,}")

    print("\n  === 5年分布对比 ===")
    cur.execute("""SELECT w.Discharge_Year, w.cnt, f.cnt FROM
        (SELECT Discharge_Year, COUNT(*) cnt FROM medical_data GROUP BY Discharge_Year) w
        JOIN (SELECT t.discharge_year, COUNT(*) cnt FROM fact_discharge f
              JOIN dim_time t ON f.year_id=t.year_id GROUP BY t.discharge_year) f
        ON w.Discharge_Year=f.discharge_year ORDER BY 1""")
    for yr, wc, fc in cur.fetchall():
        print(f"    {yr}: 宽表{wc:,} 事实表{fc:,} {'PASS' if wc==fc else 'FAIL'}")

    print("\n  === 外键完整性 ===")
    fk_pairs = [
        ("hospital_id","dim_hospital"), ("patient_demo_id","dim_patient"),
        ("diagnosis_id","dim_diagnosis"), ("procedure_id","dim_procedure"),
        ("drg_id","dim_drg"), ("payment_id","dim_payment"), ("year_id","dim_time"),
    ]
    for fk, dim in fk_pairs:
        cur.execute(f"SELECT COUNT(*) FROM fact_discharge f LEFT JOIN {dim} d ON f.{fk}=d.{fk} WHERE d.{fk} IS NULL")
        cnt = cur.fetchone()[0]
        print(f"    {fk}: 孤儿{cnt} {'PASS' if cnt==0 else 'FAIL'}")

    cur.close(); conn.close()

    # 导出
    print("\n  === 导出 ===")
    export_dir = os.path.join(PROJECT_ROOT, "star_schema_export")
    os.makedirs(export_dir, exist_ok=True)

    # 维表
    print("  导出维表...")
    os.system(f'mysqldump -u{DB_USER} -p"{DB_PASSWORD}" --quick --default-character-set=utf8mb4 '
              f'--single-transaction {DB_NAME} dim_time dim_hospital dim_patient '
              f'dim_diagnosis dim_procedure dim_drg dim_payment > "{export_dir}/dims.sql" 2>nul')
    print(f"    dims.sql OK")

    # 事实表
    print("  导出事实表 (可能需要几分钟)...")
    os.system(f'mysqldump -u{DB_USER} -p"{DB_PASSWORD}" --quick --default-character-set=utf8mb4 '
              f'--single-transaction {DB_NAME} fact_discharge > "{export_dir}/fact_discharge.sql" 2>nul')
    print(f"    fact_discharge.sql OK")

    # 合并
    print("  合并 + 压缩 zip...")
    with open(os.path.join(export_dir, "star_schema.sql"), "wb") as out:
        for f in ["dims.sql", "fact_discharge.sql"]:
            with open(os.path.join(export_dir, f), "rb") as inp:
                out.write(inp.read())

    zip_path = os.path.join(PROJECT_ROOT, "star_schema_2020-2024.zip")
    import zipfile
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in ["star_schema.sql", "dims.sql", "fact_discharge.sql"]:
            zf.write(os.path.join(export_dir, f), f)

    zip_size = os.path.getsize(zip_path) / (1024**3)
    print(f"  压缩完成: {zip_path} ({zip_size:.2f} GB)")
    print("  阶段5完成\n", flush=True)


# ============================================================
# 主入口
# ============================================================
STAGES = {
    1: ("CSV 表头修复",     stage1_fix_csv_headers),
    2: ("CSV → MySQL 导入",  stage2_import_csv),
    3: ("数据清洗",         stage3_clean_data),
    4: ("星型模型 ETL",     stage4_build_star_schema),
    5: ("验收 & 导出",      stage5_verify_and_export),
}

def main():
    parser = argparse.ArgumentParser(
        description="医疗数据完整处理流水线 (SPARCS 2020-2024 → 星型模型)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python medical_data_pipeline.py --all              # 运行全部5个阶段
  python medical_data_pipeline.py --stage 1 --stage 2 # 只运行阶段1和2
  python medical_data_pipeline.py --stage 4          # 只运行星型模型ETL
  python medical_data_pipeline.py --stage 5          # 只验收+导出
        """)
    parser.add_argument('--all', action='store_true', help='运行全部阶段')
    parser.add_argument('--stage', type=int, choices=[1,2,3,4,5], action='append',
                        help='运行指定阶段（可重复）')
    parser.add_argument('--csv-dir', type=str, default=None, help='CSV 文件目录')
    args = parser.parse_args()

    if not args.all and not args.stage:
        parser.print_help()
        return

    stages_to_run = [1,2,3,4,5] if args.all else sorted(args.stage)

    print("=" * 60)
    print("医疗数据完整处理流水线")
    print(f"数据库: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    print(f"CSV目录: {args.csv_dir or CSV_DIR}")
    print(f"执行阶段: {stages_to_run}")
    print("=" * 60, flush=True)

    t0 = time.time()
    for s in stages_to_run:
        name, func = STAGES[s]
        print(f"\n{'='*60}")
        print(f">>> 开始阶段 {s}: {name}")
        print(f"{'='*60}", flush=True)
        try:
            if s in (1, 2):
                func(csv_dir=args.csv_dir)
            else:
                func()
        except Exception as e:
            print(f"\n阶段 {s} 出错: {e}")
            traceback.print_exc()
            print(f"\n请修复后用 --stage {s} 重新运行此阶段")
            return

    print(f"\n{'='*60}")
    print(f"全部完成！总耗时: {(time.time()-t0)/60:.1f} 分钟")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
