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
import hashlib
import json
import os
import threading
import time
from decimal import Decimal

import pymysql
from flask import jsonify
from flask.json.provider import DefaultJSONProvider

# ------------------------------------------------------------
# 数据库连接（smart_health 主库，供病种/支付/质量/费用/遗留模块使用）
# 凭据优先取环境变量，默认值适配本地开发（root 空密码，127.0.0.1）
# ------------------------------------------------------------
DB = {
    "host": os.getenv("SMART_HEALTH_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("SMART_HEALTH_DB_PORT", "3306")),
    "user": os.getenv("SMART_HEALTH_DB_USER", "root"),
    "password": os.getenv("SMART_HEALTH_DB_PASSWORD", ""),
    "database": os.getenv("SMART_HEALTH_DB_DATABASE", "smart_health"),
    "charset": "utf8mb4",
}


# 每个请求线程可覆盖的数据库名（默认 None → 用 DB["database"] = smart_health）。
# 试点模块在 before_request 里 set_database("medical_db")，teardown 时清空。
_db_ctx = threading.local()


def set_database(name):
    """设置当前线程后续查询使用的数据库名；传 None 恢复默认 smart_health。"""
    _db_ctx.database = name


def get_conn():
    database = getattr(_db_ctx, "database", None) or DB["database"]
    cfg = dict(DB)
    cfg["database"] = database
    return pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **cfg)


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
# TTL 缓存（Redis 持久化 + 进程内存兜底）
# 数据为静态快照，缓存收益巨大；Redis 可跨进程/跨重启共享，连不上时自动降级内存。
# ------------------------------------------------------------
CACHE_TTL = int(os.getenv("CACHE_TTL", "86400"))  # 默认 24 小时（数据为静态快照，可调大避免冷查询重现）
CACHE_MAX = 512           # 内存兜底缓存上限（仅 Redis 不可用时生效）

_cache = {}               # 内存兜底：key -> (expire_ts, payload)
_cache_lock = threading.Lock()

# Redis 缓存后端（未启动/连接失败/未装 redis-py 时 _redis_client=None → 走内存兜底）
_redis_client = None
try:
    import redis as _redis_mod
    _redis_client = _redis_mod.Redis.from_url(
        os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
        socket_connect_timeout=2, socket_timeout=2,
        decode_responses=False,
    )
    _redis_client.ping()
except Exception:
    _redis_client = None


def _cache_rkey(key):
    return "p3cache:" + key


# ------------------------------------------------------------
# 持久化预聚合层（medical_db.api_cache）
# Redis 未启动时内存缓存会随进程消失，每次重启都要重跑 10~130s 的冷查询。
# 这里把结果落盘到 MySQL，跨重启存活；同 bigscreen_overview 的思路，但通用化。
# 数据是 2020–2024 静态快照，故不设过期；失效方式是 TRUNCATE api_cache 后重跑预热。
# ------------------------------------------------------------
DURABLE_KIND_FLASK = 1        # kind=1：Flask 侧 path?k=v 键；kind=2 由 mysql_dao 使用

_durable_ready = False        # 建表只尝试一次
_durable_lock = threading.Lock()


def _durable_conn():
    """连接 medical_db 用于缓存读写。

    注意：不能复用 get_conn() —— 它读线程局部 _db_ctx.database，默认是
    smart_health，会把缓存表建/读到错误的库里。
    """
    return pymysql.connect(
        host=os.getenv("MEDICAL_DB_HOST", DB["host"]),
        port=int(os.getenv("MEDICAL_DB_PORT", str(DB["port"]))),
        user=os.getenv("MEDICAL_DB_USER", DB["user"]),
        password=os.getenv("MEDICAL_DB_PASSWORD", DB["password"]),
        database=os.getenv("MEDICAL_DB_DATABASE", "medical_db"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def _durable_hash(key):
    return hashlib.md5(key.encode("utf-8")).hexdigest()


def _durable_get(key):
    """从 api_cache 读；表不存在/库异常一律当未命中，绝不影响请求。"""
    try:
        conn = _durable_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM api_cache WHERE kind=%s AND cache_key_hash=%s",
                    (DURABLE_KIND_FLASK, _durable_hash(key)))
                row = cur.fetchone()
        finally:
            conn.close()
        if row:
            return True, json.loads(row["payload"])
    except Exception:
        pass
    return False, None


def _durable_set(key, payload):
    """写入 api_cache（幂等 upsert）；任何异常静默跳过，内存缓存仍然有效。"""
    global _durable_ready
    try:
        conn = _durable_conn()
        try:
            with conn.cursor() as cur:
                if not _durable_ready:
                    with _durable_lock:
                        cur.execute("""
                            CREATE TABLE IF NOT EXISTS api_cache (
                              kind           TINYINT UNSIGNED NOT NULL,
                              cache_key_hash CHAR(32) CHARACTER SET ascii
                                             COLLATE ascii_bin NOT NULL,
                              cache_key      TEXT CHARACTER SET utf8mb4
                                             COLLATE utf8mb4_bin NULL,
                              payload        LONGTEXT NOT NULL,
                              updated_at     TIMESTAMP NOT NULL
                                             DEFAULT CURRENT_TIMESTAMP
                                             ON UPDATE CURRENT_TIMESTAMP,
                              PRIMARY KEY (kind, cache_key_hash)
                            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
                        _durable_ready = True
                cur.execute(
                    "INSERT INTO api_cache (kind, cache_key_hash, cache_key, payload) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE payload=VALUES(payload), "
                    "cache_key=VALUES(cache_key)",
                    (DURABLE_KIND_FLASK, _durable_hash(key), key,
                     json.dumps(payload, ensure_ascii=False, default=_json_default)))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _json_default(obj):
    """JSON 序列化兜底：Decimal 转 float，其余非原生类型（datetime 等）转 str。"""
    if isinstance(obj, Decimal):
        return float(obj)
    try:
        return str(obj)
    except Exception:
        return None


def cache_key(path, args):
    """规范化缓存键：路径 + 排序后的查询参数。"""
    items = sorted((k, str(v).strip()) for k, v in args.items())
    return path + "?" + "&".join(f"{k}={v}" for k, v in items)


def cache_get(key):
    # 优先 Redis
    if _redis_client is not None:
        try:
            raw = _redis_client.get(_cache_rkey(key))
            if raw:
                return True, json.loads(raw)
        except Exception:
            pass  # Redis 异常 → 落回内存
    # 内存兜底
    with _cache_lock:
        item = _cache.get(key)
        if item:
            expire, payload = item
            if expire > time.time():
                return True, payload
            _cache.pop(key, None)
    # 持久化兜底（跨重启存活）：命中后回填内存，后续请求走内存
    hit, payload = _durable_get(key)
    if hit:
        with _cache_lock:
            if len(_cache) < CACHE_MAX:
                _cache[key] = (time.time() + CACHE_TTL, payload)
        return True, payload
    return False, None


def cache_set(key, payload, ttl=CACHE_TTL):
    """三级写入：Redis + 内存 + api_cache。

    三级都写（而非命中一级就 return）：Redis/内存都会随进程或服务重启消失，
    只有 api_cache 能让下次冷启动直接秒开。
    """
    # Redis（可用时）
    if _redis_client is not None:
        try:
            _redis_client.setex(
                _cache_rkey(key), ttl,
                json.dumps(payload, ensure_ascii=False, default=_json_default))
        except Exception:
            pass
    # 内存
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            for k in [k for k, (e, _) in _cache.items() if e <= time.time()]:
                _cache.pop(k, None)
        if len(_cache) < CACHE_MAX:
            _cache[key] = (time.time() + ttl, payload)
    # 持久化（跨重启）
    _durable_set(key, payload)


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
