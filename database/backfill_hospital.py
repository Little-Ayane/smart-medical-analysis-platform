# -*- coding: utf-8 -*-
"""
fact_discharge 医院三列反规范化回填（批量版）
  facility_name / hospital_service_area / hospital_county ← dim_hospital (via hospital_id)
按 hospital_id 逐批 UPDATE（218 批、每批 ~4.7 万行），走 idx_hospital 索引，避免单条
UPDATE ... JOIN 全表锁。用法：python3.11 backfill_hospital.py
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
            cur.execute("SET SESSION sql_log_bin = 0")
            cur.execute("SELECT hospital_id, facility_name, hospital_service_area, "
                        "hospital_county FROM dim_hospital ORDER BY hospital_id")
            hospitals = cur.fetchall()

        total = len(hospitals)
        rows_updated = 0
        start = time.time()
        for i, h in enumerate(hospitals, 1):
            with conn.cursor() as cur:
                affected = cur.execute(
                    "UPDATE fact_discharge SET facility_name = %s, "
                    "hospital_service_area = %s, hospital_county = %s "
                    "WHERE hospital_id = %s",
                    (h["facility_name"], h["hospital_service_area"],
                     h["hospital_county"], h["hospital_id"]),
                )
            rows_updated += affected
            if i % 40 == 0 or i == total:
                rate = rows_updated / (time.time() - start)
                print(f"[{i}/{total}] hospital_id={h['hospital_id']} "
                      f"累计更新 {rows_updated} 行，{rate:.0f} 行/秒", flush=True)

        print(f"✅ 完成：共 {total} 个 hospital_id，累计更新 {rows_updated} 行，"
              f"耗时 {time.time() - start:.1f}s")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
