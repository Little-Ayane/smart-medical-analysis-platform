# -*- coding: utf-8 -*-
"""
P2 · 数据预处理与持久化模块
功能：200万+ 住院出院数据的读取、清洗、标准化、去重、结构化入库
技术：Python / Pandas / PyMySQL
用法：
    python preprocess.py --input data/hospital.tsv --db smart_health
"""
import argparse
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ------------------------------------------------------------
# 1. 大数据批量读取（分块读取，避免内存溢出）
# ------------------------------------------------------------
def load_in_chunks(path: str, sep: str = "\t", chunksize: int = 100_000):
    """按块读取 TSV/CSV，逐块 yield，解决大文件卡顿与内存溢出。"""
    logger.info("开始分块读取: %s (chunksize=%d)", path, chunksize)
    # 指定 dtype 避免低内存模式下的类型推断告警
    dtype = {
        "Age Group": "string", "Gender": "string", "Race": "string",
        "Ethnicity": "string", "Zip Code - 3 digits": "string",
        "Discharge Year": "Int32", "Length of Stay": "Int32",
        "Birth Weight": "Int32", "APR Severity of Illness Code": "Int32",
        "APR Risk of Mortality": "Int32",
    }
    for i, chunk in enumerate(pd.read_csv(path, sep=sep, dtype=dtype,
                                          low_memory=False, chunksize=chunksize)):
        logger.info("读取第 %d 块，记录数 %d", i + 1, len(chunk))
        yield chunk


# ------------------------------------------------------------
# 2. 异常处理（缺失值 / 异常值 / 去重）
# ------------------------------------------------------------
def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """按医疗业务规则清洗数据。"""
    # 2.1 非新生儿（Length of Stay 不为 Newborn 类型时按业务判断），出生体重置 N/A
    #     需求示例：非新生儿的 Birth Weight 字段设为 N/A
    if "Type of Admission" in df.columns and "Birth Weight" in df.columns:
        non_newborn = df["Type of Admission"].str.strip().str.upper() != "NEWBORN"
        df.loc[non_newborn, "Birth Weight"] = pd.NA

    # 2.2 性别标准化：统一为 M / F，非法值置 N/A
    if "Gender" in df.columns:
        df["Gender"] = df["Gender"].str.strip().str.upper()
        df.loc[~df["Gender"].isin(["M", "F"]), "Gender"] = pd.NA

    # 2.3 去除重复住院记录（基于关键字段组合去重）
    dedup_keys = [c for c in ["Permanent Facility Id", "Facility Name",
                              "Discharge Year", "CCSR Diagnosis Code",
                              "Length of Stay", "Total Charges"] if c in df.columns]
    before = len(df)
    df = df.drop_duplicates(subset=dedup_keys, keep="first")
    logger.info("去重：%d -> %d 条", before, len(df))

    return df


# ------------------------------------------------------------
# 3. 数据类型标准化
# ------------------------------------------------------------
def standardize(df: pd.DataFrame) -> pd.DataFrame:
    """统一格式与类型。"""
    # 3.1 移除 Total Charges / Total Costs 中的逗号并转浮点
    for col in ["Total Charges", "Total Costs"]:
        if col in df.columns:
            df[col] = (df[col].astype(str)
                       .str.replace(",", "", regex=False)
                       .str.replace("$", "", regex=False))
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 3.2 长度/数值字段转整数
    int_cols = ["Length of Stay", "Discharge Year", "Birth Weight",
                "APR Severity of Illness Code", "APR Risk of Mortality"]
    for col in int_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int32")

    # 3.3 字符串字段去首尾空格、统一空值为 None
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].astype("string").str.strip()
        df[col] = df[col].replace({"": None, "N/A": None, "nan": None})

    return df


# ------------------------------------------------------------
# 4. 列名映射（英文原始列 -> 中文库表字段）
# ------------------------------------------------------------
COLUMN_MAP = {
    "Hospital Service Area": "service_area",
    "Hospital County": "hospital_county",
    "Operating Certificate Number": "operating_cert_number",
    "Permanent Facility Id": "permanent_facility_id",
    "Facility Name": "facility_name",
    "Age Group": "age_group",
    "Zip Code - 3 digits": "zip3",
    "Gender": "gender",
    "Race": "race",
    "Ethnicity": "ethnicity",
    "Length of Stay": "length_of_stay",
    "Type of Admission": "type_of_admission",
    "Patient Disposition": "patient_disposition",
    "Discharge Year": "discharge_year",
    "CCSR Diagnosis Code": "ccsr_diagnosis_code",
    "CCSR Diagnosis Description": "ccsr_diagnosis_desc",
    "CCSR Procedure Code": "ccsr_procedure_code",
    "CCSR Procedure Description": "ccsr_procedure_desc",
    "APR DRG Code": "apr_drg_code",
    "APR DRG Description": "apr_drg_desc",
    "APR MDC Code": "apr_mdc_code",
    "APR MDC Description": "apr_mdc_desc",
    "APR Severity of Illness Code": "apr_severity_code",
    "APR Severity of Illness Description": "apr_severity_desc",
    "APR Risk of Mortality": "apr_risk_mortality",
    "APR Medical Surgical Description": "apr_medical_surgical",
    "Payment Typology 1": "payment_typology_1",
    "Payment Typology 2": "payment_typology_2",
    "Payment Typology 3": "payment_typology_3",
    "Birth Weight": "birth_weight",
    "Emergency Department Indicator": "ed_indicator",
    "Total Charges": "total_charges",
    "Total Costs": "total_costs",
}


# ------------------------------------------------------------
# 5. 结构化批量入库（MySQL）
# ------------------------------------------------------------
def to_mysql(df: pd.DataFrame, conn, batch: int = 5000):
    """将清洗后的结构化数据批量写入事实表（简化：直接写入事实表，维度表另建）。"""
    import pymysql

    df = df.rename(columns=COLUMN_MAP)
    cols = [c for c in COLUMN_MAP.values() if c in df.columns]

    placeholders = ", ".join(["%s"] * len(cols))
    col_names = ", ".join(cols)
    sql = f"INSERT INTO fact_inpatient_discharge ({col_names}) VALUES ({placeholders})"

    cursor = conn.cursor()
    records = df[cols].astype(object).where(pd.notnull(df[cols]), None).values.tolist()
    for i in range(0, len(records), batch):
        cursor.executemany(sql, records[i:i + batch])
        conn.commit()
        logger.info("已入库 %d/%d 条", min(i + batch, len(records)), len(records))
    cursor.close()


def connect_mysql(host="127.0.0.1", user="root", password="", db="smart_health"):
    import pymysql
    return pymysql.connect(host=host, user=user, password=password,
                           database=db, charset="utf8mb4")


# ------------------------------------------------------------
# 主流程
# ------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="原始 TSV/CSV 文件路径")
    parser.add_argument("--db", default="smart_health")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    args = parser.parse_args()

    conn = connect_mysql(args.host, args.user, args.password, args.db)

    total = 0
    for chunk in load_in_chunks(args.input):
        chunk = clean_data(chunk)        # 异常处理 + 去重
        chunk = standardize(chunk)       # 类型标准化
        to_mysql(chunk, conn)            # 批量入库
        total += len(chunk)
    logger.info("处理完成，共入库 %d 条记录", total)
    conn.close()


if __name__ == "__main__":
    main()
