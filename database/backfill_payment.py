# -*- coding: utf-8 -*-
"""
fact_discharge.payment_typology_1/2/3 反规范化回填（批量版）

为何批量：单条 `UPDATE fact_discharge JOIN dim_payment ...` 会在 128MB 缓冲池下
对 1038 万行做全表更新、锁住 ~2000 万行，实测仅 ~4500 行/秒（约需 40 分钟）。
改为按 payment_id 逐批 UPDATE（551 批、每批 ~1.8 万行），每批独立提交，
走 payment_id 索引、脏页可增量落盘，速度提升一个量级。

依赖：pymysql；凭据优先取环境变量，默认 root 空密码 + 127.0.0.1。
"""
import os
import time

import pymysql

DB = {
    "host": os.getenv("MEDICAL_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("MEDICAL_DB_PORT", "3306")),
    "user": os.getenv("MEDICAL_DB_USER", "root"),
    "password": os.getenv("MEDICAL_DB_PASSWORD", ""),
    "database": os.getenv("MEDICAL_DB_DATABASE", "medical_db"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": True,
}


def main():
    conn = pymysql.connect(**DB)
    try:
        with conn.cursor() as cur:
            # 关闭 binlog 以降低 redo 开销（本会话）
            cur.execute("SET SESSION sql_log_bin = 0")
            cur.execute("SELECT payment_id, payment_typology_1, payment_typology_2, "
                        "payment_typology_3 FROM dim_payment ORDER BY payment_id")
            payments = cur.fetchall()

        total = len(payments)
        rows_updated = 0
        start = time.time()
        for i, p in enumerate(payments, 1):
            with conn.cursor() as cur:
                affected = cur.execute(
                    "UPDATE fact_discharge SET "
                    "payment_typology_1 = %s, payment_typology_2 = %s, payment_typology_3 = %s "
                    "WHERE payment_id = %s",
                    (p["payment_typology_1"], p["payment_typology_2"],
                     p["payment_typology_3"], p["payment_id"]),
                )
            rows_updated += affected
            if i % 50 == 0 or i == total:
                rate = rows_updated / (time.time() - start)
                print(f"[{i}/{total}] payment_id={p['payment_id']} "
                      f"累计更新 {rows_updated} 行，{rate:.0f} 行/秒", flush=True)

        print(f"✅ 完成：共 {total} 个 payment_id，累计更新 {rows_updated} 行，"
              f"耗时 {time.time() - start:.1f}s")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
