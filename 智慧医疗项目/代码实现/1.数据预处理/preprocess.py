# -*- coding: utf-8 -*-
"""
P2 · 数据预处理与持久化模块（星型模型版）
功能：200万+ 住院出院数据的读取、清洗、标准化、去重，并写入星型模式数据库。
      入库顺序：先解析 4 张维度表（facility / ccsr_diagnosis / ccsr_procedure / apr_drg），
      再以维度外键写入事实表 fact_inpatient_discharge。
技术：Python / Pandas / PyMySQL
用法：
    python preprocess.py --input data/hospital.tsv --db smart_health
"""
import argparse
import logging

import numpy as np
import pandas as pd
import pymysql

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ------------------------------------------------------------
# 1. 大数据批量读取（分块读取，避免内存溢出）
# ------------------------------------------------------------
def load_in_chunks(path: str, sep: str = ",", chunksize: int = 100_000):
    """按块读取 TSV/CSV，逐块 yield，解决大文件卡顿与内存溢出。"""
    logger.info("开始分块读取: %s (chunksize=%d)", path, chunksize)
    dtype = {
        "Age Group": "string", "Gender": "string", "Race": "string",
        "Ethnicity": "string", "Zip Code - 3 digits": "string",
        "Operating Certificate Number": "string", "Permanent Facility Id": "string",
        "CCSR Diagnosis Code": "string", "CCSR Procedure Code": "string",
        "APR DRG Code": "string", "APR MDC Code": "string",
        "Emergency Department Indicator": "string",
        # 数值类字段统一按 string 读入，交给 standardize() 再转数值，原因是：
        #   ① Length of Stay 存在 "120 +" 封顶值（住院 >=120 天），强制 Int32 会读崩；
        #   ② APR Risk of Mortality 实为描述文本（Minor/Moderate/Major/Extreme），非数字代码。
        # 若在读取阶段就强制 Int32，会抛 "Unable to parse string" 直接崩溃。
        "Discharge Year": "string", "Length of Stay": "string",
        "Birth Weight": "string", "APR Severity of Illness Code": "string",
        "APR Risk of Mortality": "string",
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
    if "Type of Admission" in df.columns and "Birth Weight" in df.columns:
        non_newborn = df["Type of Admission"].str.strip().str.upper() != "NEWBORN"
        df.loc[non_newborn, "Birth Weight"] = pd.NA

    if "Gender" in df.columns:
        df["Gender"] = df["Gender"].str.strip().str.upper()
        df.loc[~df["Gender"].isin(["M", "F"]), "Gender"] = pd.NA

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
    # ① 住院天数封顶值归一：SPARCS 对 >=120 天记为 "120 +"，统一转成 120 再转数值
    if "Length of Stay" in df.columns:
        df["Length of Stay"] = (df["Length of Stay"].astype("string")
                                .str.strip()
                                .str.replace(r"\s*\+\s*$", "", regex=True))

    for col in ["Total Charges", "Total Costs"]:
        if col in df.columns:
            df[col] = (df[col].astype(str)
                       .str.replace(",", "", regex=False)
                       .str.replace("$", "", regex=False))
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # ② 注意：不再把 "APR Risk of Mortality" 纳入数值列——该列实为描述文本
    #    （Minor/Moderate/Major/Extreme），强转数值会静默置空整列。
    int_cols = ["Length of Stay", "Discharge Year", "Birth Weight",
                "APR Severity of Illness Code"]
    for col in int_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int32")

    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].astype("string").str.strip()
        df[col] = df[col].replace({"": None, "N/A": None, "nan": None})

    return df


# ------------------------------------------------------------
# 4. 维度表 / 事实表定义（原始英文列 -> 库表字段）
# ------------------------------------------------------------
# 每个维度表：表名、主键、自然键（用于去重）、字段映射
DIMENSIONS = {
    "facility": {
        "table": "dim_facility",
        "pk": "facility_id",
        "key_cols": ["Operating Certificate Number",
                     "Permanent Facility Id", "Facility Name"],
        "mapping": {
            "Operating Certificate Number": "operating_cert_number",
            "Permanent Facility Id": "permanent_facility_id",
            "Facility Name": "facility_name",
            "Hospital County": "hospital_county",
            "Hospital Service Area": "service_area",
        },
    },
    "ccsr_diagnosis": {
        "table": "dim_ccsr_diagnosis",
        "pk": "diagnosis_id",
        "key_cols": ["CCSR Diagnosis Code"],
        "mapping": {
            "CCSR Diagnosis Code": "ccsr_code",
            "CCSR Diagnosis Description": "description",
        },
    },
    "ccsr_procedure": {
        "table": "dim_ccsr_procedure",
        "pk": "procedure_id",
        "key_cols": ["CCSR Procedure Code"],
        "mapping": {
            "CCSR Procedure Code": "ccsr_code",
            "CCSR Procedure Description": "description",
        },
    },
    "apr_drg": {
        "table": "dim_apr_drg",
        "pk": "drg_id",
        "key_cols": ["APR DRG Code", "APR DRG Description"],
        "mapping": {
            "APR DRG Code": "apr_drg_code",
            "APR DRG Description": "apr_drg_desc",
            "APR MDC Code": "apr_mdc_code",
            "APR MDC Description": "apr_mdc_desc",
        },
    },
}

# 事实表字段映射（不含外键，外键由维度表解析得到）
FACT_MAPPING = {
    "Age Group": "age_group",
    "Zip Code - 3 digits": "zip3",
    "Gender": "gender",
    "Race": "race",
    "Ethnicity": "ethnicity",
    "Length of Stay": "length_of_stay",
    "Type of Admission": "type_of_admission",
    "Patient Disposition": "patient_disposition",
    "Discharge Year": "discharge_year",
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

# 事实表列顺序（与 schema.sql 对齐）
FACT_COLUMNS = [
    "facility_id", "diagnosis_id", "procedure_id", "drg_id",
    "age_group", "zip3", "gender", "race", "ethnicity",
    "length_of_stay", "type_of_admission", "patient_disposition", "discharge_year",
    "apr_severity_code", "apr_severity_desc", "apr_risk_mortality", "apr_medical_surgical",
    "payment_typology_1", "payment_typology_2", "payment_typology_3",
    "birth_weight", "ed_indicator", "total_charges", "total_costs",
]


# ------------------------------------------------------------
# 5. 维度表缓存与 upsert
# ------------------------------------------------------------
def _norm(v):
    """把 pandas/numpy 的 NA、标量统一成 Python 原生值（None 用于空）。"""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(v, "item"):
        v = v.item()
    return v


def _dim_key_series(df: pd.DataFrame, key_cols):
    """返回一列元组 key 的 Series（单列也包装成 1 元组，与缓存 key 保持一致）。"""
    if len(key_cols) == 1:
        return df[key_cols[0]].map(lambda v: (_norm(v),))
    return df[key_cols].apply(lambda r: tuple(_norm(v) for v in r), axis=1)


def load_dim_cache(conn, dim_name: str) -> dict:
    """把维度表已有记录加载到内存：{自然键: 代理键 ID}。"""
    cfg = DIMENSIONS[dim_name]
    table, pk = cfg["table"], cfg["pk"]
    key_db_cols = [cfg["mapping"][c] for c in cfg["key_cols"]]
    cache = {}
    with conn.cursor() as cur:
        cur.execute(f"SELECT {pk}, {', '.join(key_db_cols)} FROM {table}")
        for row in cur.fetchall():
            key = tuple(_norm(row[col]) for col in key_db_cols)
            cache[key] = row[pk]
    logger.info("维度表 %s 已加载 %d 条", table, len(cache))
    return cache


def init_dim_caches(conn) -> dict:
    return {name: load_dim_cache(conn, name) for name in DIMENSIONS}


def upsert_dimension(conn, df: pd.DataFrame, dim_name: str, cache: dict) -> dict:
    """把本块中新的维度值插入维度表，并更新缓存（返回更新后的缓存）。"""
    cfg = DIMENSIONS[dim_name]
    table, pk = cfg["table"], cfg["pk"]
    key_cols = [c for c in cfg["key_cols"] if c in df.columns]
    mapping = {c: db for c, db in cfg["mapping"].items() if c in df.columns}
    if not key_cols or not mapping:
        return cache

    # 按自然键去重（保留首条），再补全其余映射字段
    dim_df = df[list(mapping.keys())].drop_duplicates(subset=key_cols, keep="first")
    db_cols = [mapping[c] for c in mapping.keys()]

    new_count = 0
    with conn.cursor() as cur:
        sql = (f"INSERT INTO {table} ({', '.join(db_cols)}) "
               f"VALUES ({', '.join(['%s'] * len(db_cols))})")
        for _, row in dim_df.iterrows():
            key = tuple(_norm(row[c]) for c in key_cols)
            # 自然键含空的维度行（如"无手术"记录的空 CCSR Procedure Code）不写维度表，
            # 对应事实行经 cache.get() 映射为 NULL 外键，与 schema 的 DEFAULT NULL 一致
            if key in cache or any(k is None for k in key):
                continue
            values = [_norm(row[c]) for c in mapping.keys()]
            cur.execute(sql, values)
            cache[key] = cur.lastrowid
            new_count += 1
    conn.commit()
    if new_count:
        logger.info("维度表 %s 新增 %d 条", table, new_count)
    return cache


def map_fact_ids(df: pd.DataFrame, caches: dict) -> pd.DataFrame:
    """根据维度缓存，为事实表行解析出 4 个外键。"""
    fact = pd.DataFrame(index=df.index)
    fk_map = {
        "facility": "facility_id",
        "ccsr_diagnosis": "diagnosis_id",
        "ccsr_procedure": "procedure_id",
        "apr_drg": "drg_id",
    }
    for dim_name, fk_col in fk_map.items():
        key_cols = [c for c in DIMENSIONS[dim_name]["key_cols"] if c in df.columns]
        if key_cols:
            cache = caches[dim_name]
            keys = _dim_key_series(df, key_cols)
            fact[fk_col] = keys.map(lambda k: cache.get(k)).astype("Int64")
        else:
            fact[fk_col] = pd.NA
    return fact


def insert_fact(conn, fact_df: pd.DataFrame, batch: int = 5000):
    """把带外键的事实行批量写入事实表。"""
    cols = [c for c in FACT_COLUMNS if c in fact_df.columns]
    placeholders = ", ".join(["%s"] * len(cols))
    col_names = ", ".join(cols)
    sql = f"INSERT INTO fact_inpatient_discharge ({col_names}) VALUES ({placeholders})"

    records = fact_df[cols].astype(object).where(pd.notnull(fact_df[cols]), None).values.tolist()
    with conn.cursor() as cur:
        for i in range(0, len(records), batch):
            cur.executemany(sql, records[i:i + batch])
            conn.commit()
            logger.info("事实表已入库 %d/%d 条", min(i + batch, len(records)), len(records))


def load_chunk(conn, df: pd.DataFrame, caches: dict) -> int:
    """处理一个块：维度 upsert -> 解析外键 -> 写事实表。"""
    for dim_name in DIMENSIONS:
        caches[dim_name] = upsert_dimension(conn, df, dim_name, caches[dim_name])

    fact_ids = map_fact_ids(df, caches)
    fact_df = df.rename(columns=FACT_MAPPING)[list(FACT_MAPPING.values())]
    fact_df = pd.concat([fact_ids, fact_df], axis=1)
    insert_fact(conn, fact_df)
    return len(fact_df)


# ------------------------------------------------------------
# 6. 连接与主流程
# ------------------------------------------------------------
def connect_mysql(host="127.0.0.1", user="root", password="", db="smart_health"):
    return pymysql.connect(host=host, user=user, password=password,
                           database=db, charset="utf8mb4",
                           cursorclass=pymysql.cursors.DictCursor)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="原始 TSV/CSV 文件路径")
    parser.add_argument("--sep", default=",", help="分隔符，CSV 用 \",\"，TSV 用 \"\\t\"")
    parser.add_argument("--db", default="smart_health")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default="")
    args = parser.parse_args()

    conn = connect_mysql(args.host, args.user, args.password, args.db)
    caches = init_dim_caches(conn)

    total = 0
    for chunk in load_in_chunks(args.input, sep=args.sep):
        chunk = clean_data(chunk)          # 异常处理 + 去重
        chunk = standardize(chunk)         # 类型标准化
        total += load_chunk(conn, chunk, caches)

    logger.info("处理完成，共入库 %d 条事实记录", total)
    conn.close()


if __name__ == "__main__":
    main()
