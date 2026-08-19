# -*- coding: utf-8 -*-
"""
P3 · 分析服务公共层（病种手术分析 + 支付分析 两模块共用）
功能：数据库连接、统一信封（扩展 filters/cached）、过滤白名单解析（防注入）、
      进程内 TTL 缓存、Decimal JSON 序列化修复、带缓存聚合执行器。
约定：
    - 所有聚合查询一律"先按事实表列/外键 GROUP BY 预聚合（LIMIT topN），后 JOIN 小维度表取名"，
      禁止在 GROUP BY 中直接使用维度表列（实测 4.3s vs 0.7s）。
    - WHERE 只允许由本文件白名单生成，值全部 %s 参数化。
"""
import json
import threading
import time
from decimal import Decimal

import pymysql
from flask import jsonify
from flask.json.provider import DefaultJSONProvider

# ------------------------------------------------------------
# 数据库连接
# ------------------------------------------------------------
DB = {
    "host": "127.0.0.1",
    "user": "root",
    "password": "",
    "database": "smart_health",
    "charset": "utf8mb4",
}


def get_conn():
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **DB)


# ------------------------------------------------------------
# 常量：严重程度 code<->desc（含 Unknown 组）
# ------------------------------------------------------------
SEVERITY_CODE_TO_DESC = {1: "Minor", 2: "Moderate", 3: "Major", 4: "Extreme",
                         None: "Unknown"}
# 名称映射键统一大写，与 _norm_severity 的 v.upper() 对齐
SEVERITY_NAME_TO_CODE = {v.upper(): k for k, v in SEVERITY_CODE_TO_DESC.items() if k}

# 年龄段业务顺序（金字塔/热力图等均按此排序）
AGE_GROUPS = ["0 to 17", "18 to 29", "30 to 49", "50 to 69", "70 or Older"]
AGE_ORDER_SQL = "FIELD(age_group, '0 to 17','18 to 29','30 to 49','50 to 69','70 or Older')"


# ------------------------------------------------------------
# 统一响应信封（在既有 code/message/data/meta 上扩展，只增不改）
# ------------------------------------------------------------
def envelope(data, dimension=None, metric=None, total_records=None, query_ms=0,
             filters=None, cached=False, **extra):
    meta = {
        "dimension": dimension,
        "metric": metric,
        "total_records": total_records,
        "filters": filters or {},
        "cached": cached,
        "query_ms": query_ms,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    meta.update(extra)          # null_excluded / top_dim1 等端点级附加字段
    return jsonify({"code": 0, "message": "success", "data": data, "meta": meta})


def error(code, message):
    return jsonify({"code": code, "message": message, "data": None, "meta": {}}), 200


# ------------------------------------------------------------
# Decimal JSON 序列化修复
# PyMySQL 对 DECIMAL 列返回 decimal.Decimal，Flask 默认 JSON provider
# 无法序列化，jsonify 直接抛 TypeError -> 500。所有费用类聚合都会踩中。
# ------------------------------------------------------------
class DecimalJSONProvider(DefaultJSONProvider):
    @staticmethod
    def default(o):
        if isinstance(o, Decimal):
            return float(o)
        return DefaultJSONProvider.default(o)


def apply_json_provider(app):
    app.json = DecimalJSONProvider(app)


# ------------------------------------------------------------
# 过滤参数白名单（防 SQL 注入：WHERE 片段只由本表生成，值全 %s 参数化）
# ------------------------------------------------------------
class BadRequest(Exception):
    """参数校验失败 -> 400 错误码信封。"""


def _norm_year(v):
    v = v.strip()
    if v != "2021":
        raise BadRequest(f"当前数据仅含 2021 年，year 仅支持 2021，收到: {v}")
    return 2021


def _norm_gender(v):
    v = v.strip().upper()
    if v not in ("M", "F"):
        raise BadRequest(f"gender 仅支持 M/F，收到: {v}")
    return v


def _norm_severity(v):
    v = v.strip()
    if v in ("1", "2", "3", "4"):
        return int(v)
    code = SEVERITY_NAME_TO_CODE.get(v.upper())
    if code:
        return code
    raise BadRequest(f"severity 仅支持 1-4 或 Minor/Moderate/Major/Extreme，收到: {v}")


# 参数名 -> (事实表列表达式, 规范化函数)
FILTER_COLS = {
    "year":      ("f.discharge_year", _norm_year),
    "gender":    ("f.gender", _norm_gender),
    "age_group": ("f.age_group", lambda v: v.strip()),
    "payment":   ("f.payment_typology_1", lambda v: v.strip()),
    "payment2":  ("f.payment_typology_2", lambda v: v.strip()),
    "payment3":  ("f.payment_typology_3", lambda v: v.strip()),
    "severity":  ("f.apr_severity_code", _norm_severity),
    # 以下五类走 DIM_SUBQUERY 分支（维度值 -> 外键 IN 子查询），norm_fn 不参与
    "diagnosis": ("f.diagnosis_id", None),
    "procedure": ("f.procedure_id", None),
    "service_area": ("f.facility_id", None),
    "county": ("f.facility_id", None),
    "facility": ("f.facility_id", None),
}

# 维度值类过滤：翻译为外键 IN (SELECT ...) 子查询（维度表均 <=477 行，代价可忽略）
# 参数名 -> (维度表, 主键, 子查询条件, 参数化值函数)
DIM_SUBQUERY = {
    "diagnosis": ("dim_ccsr_diagnosis", "diagnosis_id",
                  "ccsr_code = %s OR description = %s",
                  lambda v: (v.strip().upper(), v.strip())),
    "procedure": ("dim_ccsr_procedure", "procedure_id",
                  "ccsr_code = %s OR description = %s",
                  lambda v: (v.strip().upper(), v.strip())),
    "service_area": ("dim_facility", "facility_id", "service_area = %s",
                     lambda v: (v.strip(),)),
    "county": ("dim_facility", "facility_id", "hospital_county = %s",
               lambda v: (v.strip(),)),
    "facility": ("dim_facility", "facility_id", "facility_name = %s",
                 lambda v: (v.strip(),)),
}


def parse_filters(args):
    """解析请求参数为 (where 片段列表, 参数列表, 规范化回显 dict)。
    只认白名单内的过滤参数，其余参数（top/metric 等）忽略；非法值抛 BadRequest。"""
    where, params, norm = [], [], {}
    for name, value in args.items():
        if name not in FILTER_COLS:
            continue
        col, norm_fn = FILTER_COLS[name]
        if name in DIM_SUBQUERY:
            table, pk, cond, val_fn = DIM_SUBQUERY[name]
            vals = val_fn(value)
            where.append(f"{col} IN (SELECT {pk} FROM {table} WHERE {cond})")
            params.extend(vals)
            norm[name] = vals[0]
        else:
            v = norm_fn(value)
            where.append(f"{col} = %s")
            params.append(v)
            norm[name] = v
    return where, params, norm


# ------------------------------------------------------------
# 参数解析小工具
# ------------------------------------------------------------
def parse_choice(args, name, allowed, default):
    """白名单单选参数（dimension/level/by/mode 等）。"""
    v = args.get(name, default)
    if v not in allowed:
        raise BadRequest(f"{name} 仅支持 {sorted(allowed)}，收到: {v}")
    return v


def parse_metric(args, allowed, default="count"):
    return parse_choice(args, "metric", allowed, default)


def parse_top(args, default=20, cap=100, name="top"):
    raw = args.get(name, default)
    try:
        top = int(raw)
    except (TypeError, ValueError):
        raise BadRequest(f"{name} 必须为整数，收到: {raw}")
    return min(max(top, 1), cap)


# 通用指标表达式（用于 SELECT 聚合列）
METRICS = {
    "count": "COUNT(*)",
    "total_charges": "ROUND(SUM(total_charges), 2)",
    "avg_charges": "ROUND(AVG(total_charges), 2)",
    "avg_los": "ROUND(AVG(length_of_stay), 2)",
}


# ------------------------------------------------------------
# 进程内 TTL 缓存（数据为静态单年度快照，缓存收益巨大）
# ------------------------------------------------------------
CACHE_TTL = 3600          # 默认 1 小时
CACHE_MAX = 512           # 最多缓存条目，满则淘汰已过期项

_cache = {}               # key -> (expire_ts, payload)
_cache_lock = threading.Lock()


def cache_key(path, args):
    """规范化缓存键：路径 + 排序后的查询参数。"""
    items = sorted((k, str(v).strip()) for k, v in args.items())
    return path + "?" + "&".join(f"{k}={v}" for k, v in items)


def cache_get(key):
    with _cache_lock:
        item = _cache.get(key)
        if item:
            expire, payload = item
            if expire > time.time():
                return True, payload
            _cache.pop(key, None)
    return False, None


def cache_set(key, payload, ttl=CACHE_TTL):
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            for k in [k for k, (e, _) in _cache.items() if e <= time.time()]:
                _cache.pop(k, None)
        if len(_cache) < CACHE_MAX:
            _cache[key] = (time.time() + ttl, payload)


# ------------------------------------------------------------
# 查询与缓存执行器
# ------------------------------------------------------------
def timed_query(sql, params=None):
    """执行查询，返回 (rows, 耗时 ms)。"""
    start = time.time()
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            rows = cur.fetchall()
    finally:
        conn.close()
    return rows, int((time.time() - start) * 1000)


def execute_cached(path, args, sql, params=None, count_sql=None, count_params=None,
                   post=None, extras=None, ttl=CACHE_TTL):
    """带 TTL 缓存的聚合执行器，返回 (data, total_records, query_ms, cached, extras)。
    - post(rows) -> data：行级加工（映射名称、计算 pct 等），结果随缓存保存
    - count_sql 存在时单独统计 total_records（与查询同过滤口径）
    - extras：随缓存一起保存的 meta 附加字段（null_excluded 等），
      传 callable 时仅在缓存未命中时调用（避免命中后仍跑 COUNT 查询）
    """
    key = cache_key(path, args)
    hit, payload = cache_get(key)
    if hit:
        return payload["data"], payload["total"], 0, True, payload["extras"]

    start = time.time()
    rows, _ = timed_query(sql, params)
    data = post(rows) if post else rows
    total = None
    if count_sql:
        crow, _ = timed_query(count_sql, count_params)
        total = crow[0]["c"] if crow else None
    ms = int((time.time() - start) * 1000)
    extra = extras() if callable(extras) else (extras or {})
    payload = {"data": data, "total": total, "extras": extra}
    cache_set(key, payload, ttl)
    return data, total, ms, False, extra


# ------------------------------------------------------------
# 维度名称字典（供 post 阶段为外键取名，维度表小、查询快）
# ------------------------------------------------------------
def fetch_dim_names(table, pk, code_col="ccsr_code", name_col="description"):
    """返回 {pk: (code, name)} 全量映射。"""
    rows, _ = timed_query(
        f"SELECT {pk} AS id, {code_col} AS code, {name_col} AS name FROM {table}")
    return {r["id"]: (r["code"], r["name"]) for r in rows}


def fetch_facility_map():
    """返回 {facility_id: (name, county, service_area)}。"""
    rows, _ = timed_query(
        "SELECT facility_id AS id, facility_name AS name, hospital_county AS county, "
        "service_area AS area FROM dim_facility")
    return {r["id"]: (r["name"], r["county"], r["area"]) for r in rows}
