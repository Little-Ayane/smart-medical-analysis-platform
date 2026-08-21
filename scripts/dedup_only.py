"""
只做去重：按关键字段分组，保留每组 fact_id 最小的那条
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

# 当前行数
cur.execute("SELECT COUNT(*) FROM medical_data")
before = cur.fetchone()[0]
print(f"📊 去重前行数: {before:,}")

# 用临时表去重
print("🧹 创建去重临时表...")
cur.execute("CREATE TABLE medical_data_deduped LIKE medical_data")

print("🧹 插入去重数据（保留每组第一条）...")
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
after = cur.fetchone()[0]
removed = before - after
print(f"  ✅ 去重后行数: {after:,}")
print(f"  🗑️  删除重复行: {removed:,}")

# 替换原表
print("🔄 替换原表...")
cur.execute("DROP TABLE medical_data")
cur.execute("RENAME TABLE medical_data_deduped TO medical_data")
conn.commit()

# 最终验证
cur.execute("SELECT COUNT(*) FROM medical_data")
final = cur.fetchone()[0]
print(f"\n📊 最终总行数: {final:,}")

# 验证无重复
cur.execute("""
    SELECT COUNT(*) FROM (
        SELECT 1 FROM medical_data
        GROUP BY Permanent_Facility_Id, Age_Group, Gender, Race, Ethnicity,
                 Zip_Code_3digits, CCSR_Diagnosis_Code, APR_DRG_Code,
                 Length_of_Stay, Total_Charges, Total_Costs
        HAVING COUNT(*) > 1
    ) t
""")
dup = cur.fetchone()[0]
print(f"  重复组: {dup} {'✅' if dup == 0 else '⚠️'}")

# 性别
print("\n--- 性别 ---")
cur.execute("SELECT Gender, COUNT(*) FROM medical_data GROUP BY Gender")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]:,}")

conn.close()
print("\n🎉 去重完成！数据彻底干净了！")