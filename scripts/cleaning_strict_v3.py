"""
精准清洗 v3:
- 跳过数值类型字段（APR_MDC_Code 等），避免 'nan' 比较报错
- 用 try-except 兜底，确保跑完不中断
- DELETE 已执行过的不会重复删（rowcount=0，安全）
"""
import pymysql

DB = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "Csu@Boy727620zy",      # ← 改成你的真实密码！
    "database": "medical_db",
    "charset": "utf8mb4"
}

conn = pymysql.connect(**DB)
cur = conn.cursor()

# ---- 当前行数 ----
cur.execute("SELECT COUNT(*) FROM medical_data")
before = cur.fetchone()[0]
print(f"📊 当前总行数: {before:,}")

# ---- 1. 再跑一次 DELETE（已删的行不受影响，rowcount=0）----
print("\n🗑️  补充删除检查...")
delete_checks = [
    ("Gender", "= 'U'"),
    ("Permanent_Facility_Id", "IS NULL"),
    ("Zip_Code_3digits", "= 'nan'"),
]
for field, condition in delete_checks:
    cur.execute(f"SELECT COUNT(*) FROM medical_data WHERE `{field}` {condition}")
    cnt = cur.fetchone()[0]
    if cnt > 0:
        cur.execute(f"DELETE FROM medical_data WHERE `{field}` {condition}")
        print(f"  🗑️  {field} {condition}: 再删 {cur.rowcount} 行")
    else:
        print(f"  ✅ {field} {condition}: 已清理（0 行）")

conn.commit()

# ---- 2. 把 'nan' 字符串更新为 NULL（只处理确定是字符串的字段）----
print("\n🔧 将 'nan' 字符串转为 NULL...")

# 只保留 VARCHAR/TEXT 类型的字段，去掉了数值型的 APR_MDC_Code 和 APR_Severity_of_Illness_Code
nan_fields_to_fix = [
    "Hospital_Service_Area",
    "Hospital_County",
    "CCSR_Diagnosis_Code",
    "CCSR_Diagnosis_Description",
    "CCSR_Procedure_Code",
    "CCSR_Procedure_Description",
    "APR_Severity_of_Illness_Description",   # 字符串（Minor/Moderate/Major）
    "APR_Risk_of_Mortality",                  # 字符串（Minor/Major/Extreme）
    "Payment_Typology_2",
    "Payment_Typology_3",
]

for field in nan_fields_to_fix:
    try:
        cur.execute(f"UPDATE medical_data SET `{field}` = NULL WHERE `{field}` = 'nan'")
        affected = cur.rowcount
        if affected > 0:
            print(f"  ✅ {field}: {affected:,} 行更新为 NULL")
        else:
            print(f"  ✅ {field}: 无需更新")
    except Exception as e:
        print(f"  ⚠️ {field}: 跳过（{e}）")

conn.commit()
print("✅ 所有 UPDATE 已提交")

# ---- 3. 验证 ----
cur.execute("SELECT COUNT(*) FROM medical_data")
after = cur.fetchone()[0]
print(f"\n📊 最终总行数: {after:,}")

print("\n--- 性别分布 ---")
cur.execute("SELECT Gender, COUNT(*) FROM medical_data GROUP BY Gender")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]:,}")

print("\n--- 残留 'nan' 检查 ---")
# 检查数值字段里是否还有 'nan'（应该没有，因为存不进去）
check_str_fields = ["Hospital_Service_Area", "Zip_Code_3digits",
                    "Payment_Typology_2", "Payment_Typology_3"]
for f in check_str_fields:
    try:
        cur.execute(f"SELECT COUNT(*) FROM medical_data WHERE `{f}` = 'nan'")
        c = cur.fetchone()[0]
        status = "✅" if c == 0 else "⚠️"
        print(f"  {status} {f}: {c}")
    except:
        print(f"  ⏭️ {f}: 跳过（数值类型）")

conn.close()
print("\n🎉 精准清洗 v3 完成！")