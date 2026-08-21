"""
精准清洗 v2:
1. 删除 Gender='U' 的行
2. 删除 Permanent_Facility_Id 为 NULL 的行（医院信息缺失）
3. 删除 Zip_Code_3digits='nan' 的行（邮编缺失）
4. 把所有 'nan' 字符串更新为真正的 NULL（不删行）
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

# ---- 清洗前 ----
cur.execute("SELECT COUNT(*) FROM medical_data")
before = cur.fetchone()[0]
print(f"📊 清洗前总行数: {before:,}")

deleted_total = 0

# ---- 1. 删除 Gender = 'U' ----
cur.execute("SELECT COUNT(*) FROM medical_data WHERE Gender = 'U'")
u_count = cur.fetchone()[0]
print(f"  🔍 Gender='U': {u_count} 行")
cur.execute("DELETE FROM medical_data WHERE Gender = 'U'")
deleted_total += cur.rowcount

# ---- 2. 删除 Permanent_Facility_Id IS NULL ----
cur.execute("SELECT COUNT(*) FROM medical_data WHERE Permanent_Facility_Id IS NULL")
null_facility = cur.fetchone()[0]
print(f"  🔍 Permanent_Facility_Id IS NULL: {null_facility} 行")
cur.execute("DELETE FROM medical_data WHERE Permanent_Facility_Id IS NULL")
deleted_total += cur.rowcount

# ---- 3. 删除 Zip_Code_3digits = 'nan' ----
cur.execute("SELECT COUNT(*) FROM medical_data WHERE Zip_Code_3digits = 'nan'")
nan_zip = cur.fetchone()[0]
print(f"  🔍 Zip_Code_3digits='nan': {nan_zip} 行")
cur.execute("DELETE FROM medical_data WHERE Zip_Code_3digits = 'nan'")
deleted_total += cur.rowcount

conn.commit()
print(f"🗑️  共删除: {deleted_total:,} 行")

# ---- 4. 把 'nan' 字符串更新为真正的 NULL ----
print("\n🔧 将 'nan' 字符串转为 NULL...")

nan_fields_to_fix = [
    "Hospital_Service_Area",
    "Hospital_County",
    "CCSR_Diagnosis_Code",
    "CCSR_Diagnosis_Description",
    "CCSR_Procedure_Code",
    "CCSR_Procedure_Description",
    "APR_MDC_Code",
    "APR_Severity_of_Illness_Code",
    "APR_Severity_of_Illness_Description",
    "APR_Risk_of_Mortality",
    "Payment_Typology_2",
    "Payment_Typology_3",
]

for field in nan_fields_to_fix:
    cur.execute(f"UPDATE medical_data SET `{field}` = NULL WHERE `{field}` = 'nan'")
    affected = cur.rowcount
    if affected > 0:
        print(f"  ✅ {field}: {affected:,} 行更新为 NULL")

conn.commit()

# ---- 清洗后验证 ----
cur.execute("SELECT COUNT(*) FROM medical_data")
after = cur.fetchone()[0]
print(f"\n📊 清洗后总行数: {after:,}")
print(f"📈 保留率: {after/before*100:.2f}%")

# 验证性别
print("\n--- 性别分布（清洗后）---")
cur.execute("SELECT Gender, COUNT(*) FROM medical_data GROUP BY Gender")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]:,}")

# 验证 NULL 情况
print("\n--- 残留空值检查 ---")
check_fields = ["Permanent_Facility_Id", "Zip_Code_3digits", "Gender"]
for f in check_fields:
    cur.execute(f"SELECT COUNT(*) FROM medical_data WHERE `{f}` IS NULL OR TRIM(COALESCE(`{f}`,'')) = ''")
    c = cur.fetchone()[0]
    status = "✅" if c == 0 else "⚠️"
    print(f"  {status} {f} 空值: {c}")

conn.close()
print("\n🎉 精准清洗完成！")