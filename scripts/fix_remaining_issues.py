"""
修复剩余问题:
1. 删除 CCSR_Diagnosis_Code IS NULL 的行（无诊断，无效记录）
2. 把 APR_Severity_of_Illness_Code 的 'nan' 转 NULL
3. 去重（按关键字段分组，保留 id 最小的那条）
"""
import pymysql

DB = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "Csu@Boy727620zy",      # ← 改成真实密码！
    "database": "medical_db",
    "charset": "utf8mb4"
}

conn = pymysql.connect(**DB)
cur = conn.cursor()

# ---- 当前行数 ----
cur.execute("SELECT COUNT(*) FROM medical_data")
before = cur.fetchone()[0]
print(f"📊 修复前行数: {before:,}")

# ---- 1. 删除诊断编码为 NULL 的行 ----
cur.execute("SELECT COUNT(*) FROM medical_data WHERE CCSR_Diagnosis_Code IS NULL")
null_diag = cur.fetchone()[0]
print(f"\n🗑️  诊断编码为 NULL: {null_diag} 行 → 删除")
cur.execute("DELETE FROM medical_data WHERE CCSR_Diagnosis_Code IS NULL")
conn.commit()
print(f"  ✅ 已删除 {cur.rowcount} 行")

# ---- 2. APR_Severity_of_Illness_Code 'nan' → NULL ----
cur.execute("SELECT COUNT(*) FROM medical_data WHERE APR_Severity_of_Illness_Code = 'nan'")
nan_sev = cur.fetchone()[0]
print(f"\n🔧 APR_Severity_of_Illness_Code 'nan': {nan_sev} 行 → 转 NULL")
cur.execute("UPDATE medical_data SET APR_Severity_of_Illness_Code = NULL WHERE APR_Severity_of_Illness_Code = 'nan'")
conn.commit()
print(f"  ✅ 已更新 {cur.rowcount} 行")

# ---- 3. 去重 ----
print(f"\n🧹 开始去重...")

# 先看看重复组数
cur.execute("""
    SELECT COUNT(*) FROM (
        SELECT 1 FROM medical_data
        GROUP BY Permanent_Facility_Id, Age_Group, Gender, Race, Ethnicity,
                 Zip_Code_3digits, CCSR_Diagnosis_Code, APR_DRG_Code,
                 Length_of_Stay, Total_Charges, Total_Costs
        HAVING COUNT(*) > 1
    ) t
""")
dup_groups = cur.fetchone()[0]
print(f"  重复组数: {dup_groups:,}")

# 用临时表去重（保留每组 id 最小的那条）
cur.execute("CREATE TABLE medical_data_deduped LIKE medical_data")

cur.execute("""
    INSERT INTO medical_data_deduped
    SELECT * FROM medical_data
    WHERE fact_id IN (
        SELECT MIN(fact_id) FROM medical_data
        GROUP BY Permanent_Facility_Id, Age_Group, Gender, Race, Ethnicity,
                 Zip_Code_3digits, CCSR_Diagnosis_Code, APR_DRG_Code,
                 Length_of_Stay, Total_Charges, Total_Costs
    )
""")
conn.commit()

cur.execute("SELECT COUNT(*) FROM medical_data_deduped")
deduped_count = cur.fetchone()[0]
print(f"  去重后行数: {deduped_count:,}")

# 替换原表
cur.execute("DROP TABLE medical_data")
cur.execute("RENAME TABLE medical_data_deduped TO medical_data")
conn.commit()

deleted_dup = before - null_diag - deduped_count
print(f"  ✅ 删除重复行: ~{deleted_dup:,} 行")

# ---- 最终验证 ----
cur.execute("SELECT COUNT(*) FROM medical_data")
final = cur.fetchone()[0]
print(f"\n📊 最终行数: {final:,}")

# 验证诊断编码无 NULL
cur.execute("SELECT COUNT(*) FROM medical_data WHERE CCSR_Diagnosis_Code IS NULL")
d = cur.fetchone()[0]
print(f"  诊断编码 NULL: {d} ✅" if d == 0 else f"  ⚠️ 诊断编码 NULL: {d}")

# 验证 severity 'nan' 无残留
cur.execute("SELECT COUNT(*) FROM medical_data WHERE APR_Severity_of_Illness_Code = 'nan'")
s = cur.fetchone()[0]
print(f"  Severity 'nan': {s} ✅" if s == 0 else f"  ⚠️ Severity 'nan': {s}")

# 验证重复
cur.execute("""
    SELECT COUNT(*) FROM (
        SELECT 1 FROM medical_data
        GROUP BY Permanent_Facility_Id, Age_Group, Gender, Race, Ethnicity,
                 Zip_Code_3digits, CCSR_Diagnosis_Code, APR_DRG_Code,
                 Length_of_Stay, Total_Charges, Total_Costs
        HAVING COUNT(*) > 1
    ) t
""")
r = cur.fetchone()[0]
print(f"  重复组: {r} ✅" if r == 0 else f"  ⚠️ 重复组: {r}")

# 性别
print("\n--- 性别 ---")
cur.execute("SELECT Gender, COUNT(*) FROM medical_data GROUP BY Gender")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]:,}")

conn.close()
print("\n🎉 修复完成！")