"""
数据全面体检 - 检查所有异常数据
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

issues_found = 0

def report(title, count, detail=""):
    global issues_found
    if count > 0:
        issues_found += 1
        print(f"  ⚠️  {title}: {count:,} 行 {detail}")
    else:
        print(f"  ✅ {title}: 正常")

print("=" * 65)
print("  🩺 medical_data 全面体检")
print("=" * 65)

# ---------- 1. 总行数 ----------
cur.execute("SELECT COUNT(*) FROM medical_data")
total = cur.fetchone()[0]
print(f"\n📊 总行数: {total:,}\n")

# ---------- 2. 空值检查 ----------
print("【1】空值 / NULL 检查")
fields_check = [
    "Gender", "Age_Group", "Race", "Ethnicity",
    "Zip_Code_3digits", "Type_of_Admission", "Patient_Disposition",
    "CCSR_Diagnosis_Code", "CCSR_Diagnosis_Description",
    "APR_DRG_Code", "APR_DRG_Description",
    "APR_Severity_of_Illness_Code", "APR_Severity_of_Illness_Description",
    "APR_Risk_of_Mortality", "APR_Medical_Surgical_Description",
    "Payment_Typology_1", "Discharge_Year",
    "Length_of_Stay", "Total_Charges", "Total_Costs",
    "Permanent_Facility_Id", "Facility_Name",
    "Hospital_Service_Area", "Hospital_County",
]
for f in fields_check:
    cur.execute(f"SELECT COUNT(*) FROM medical_data WHERE `{f}` IS NULL OR TRIM(COALESCE(`{f}`,'')) = ''")
    c = cur.fetchone()[0]
    report(f"{f} 空值", c)

# ---------- 3. 'nan' / 'NaN' 残留 ----------
print("\n【2】'nan' / 'NaN' 字符串残留")
for f in fields_check:
    try:
        cur.execute(f"SELECT COUNT(*) FROM medical_data WHERE `{f}` = 'nan' OR `{f}` = 'NaN'")
        c = cur.fetchone()[0]
        report(f"{f} 'nan'", c)
    except:
        pass  # 数值字段跳过

# ---------- 4. 性别异常 ----------
print("\n【3】性别异常")
cur.execute("SELECT Gender, COUNT(*) FROM medical_data GROUP BY Gender")
genders = cur.fetchall()
print(f"  性别分布:")
for g, c in genders:
    flag = "⚠️" if g not in ('M', 'F') else "✅"
    print(f"    {flag} '{g}': {c:,}")
for g, c in genders:
    if g not in ('M', 'F'):
        issues_found += 1

# ---------- 5. 年龄组异常 ----------
print("\n【4】年龄段异常")
valid_ages = ('0-17', '18-29', '30-49', '50-69', '70 or Older')
cur.execute(f"SELECT Age_Group, COUNT(*) FROM medical_data WHERE Age_Group NOT IN {valid_ages} GROUP BY Age_Group")
bad_ages = cur.fetchall()
if bad_ages:
    for a, c in bad_ages:
        report(f"异常年龄段 '{a}'", c)
else:
    print("  ✅ 所有年龄段均在合法范围内")

# ---------- 6. 数值范围异常 ----------
print("\n【5】数值字段范围检查")

# Length_of_Stay 应该是 >= 0，且极端值 < 365
cur.execute("SELECT COUNT(*) FROM medical_data WHERE Length_of_Stay < 0")
report("Length_of_Stay < 0", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM medical_data WHERE Length_of_Stay > 365")
report("Length_of_Stay > 365天(异常长)", cur.fetchone()[0])

# Total_Charges 和 Total_Costs 应该 >= 0
cur.execute("SELECT COUNT(*) FROM medical_data WHERE Total_Charges < 0")
report("Total_Charges < 0", cur.fetchone()[0])
cur.execute("SELECT COUNT(*) FROM medical_data WHERE Total_Costs < 0")
report("Total_Costs < 0", cur.fetchone()[0])

# Total_Charges 极端值（比如超过 1000 万）
cur.execute("SELECT COUNT(*) FROM medical_data WHERE Total_Charges > 10000000")
report("Total_Charges > 1000万(极端值)", cur.fetchone()[0])

# Birth_Weight 范围（0~20000 克，约 44 磅）
cur.execute("SELECT COUNT(*) FROM medical_data WHERE Birth_Weight < 0 OR Birth_Weight > 20000")
report("Birth_Weight 超出合理范围", cur.fetchone()[0])

# ---------- 7. 枚举字段异常 ----------
print("\n【6】枚举字段合法性")

# Emergency_Department_Indicator 应该只有 Y/N
cur.execute("SELECT DISTINCT Emergency_Department_Indicator FROM medical_data")
eds = [r[0] for r in cur.fetchall()]
bad_ed = [e for e in eds if e not in ('Y', 'N')]
if bad_ed:
    report(f"Emergency_Dept 非法值 {bad_ed}", len(bad_ed))
else:
    print("  ✅ Emergency_Department_Indicator 仅含 Y/N")

# APR_Severity 合法值
cur.execute("SELECT DISTINCT APR_Severity_of_Illness_Description FROM medical_data")
sevs = [r[0] for r in cur.fetchall()]
valid_sev = ('Minor', 'Moderate', 'Major', 'Extreme')
bad_sev = [s for s in sevs if s not in valid_sev]
if bad_sev:
    report(f"APR_Severity 非法值 {bad_sev}", len(bad_sev))
else:
    print("  ✅ APR_Severity_of_Illness_Description 合法")

# ---------- 8. 重复行检查 ----------
print("\n【7】完全重复行")
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
report("重复记录组(关键字段完全相同)", dup_groups)

# ---------- 9. 关键字段组合空 ----------
print("\n【8】关键外键字段 NULL 检查")
fk_fields = [
    ("Permanent_Facility_Id", "医院ID"),
    ("CCSR_Diagnosis_Code", "诊断编码"),
    ("APR_DRG_Code", "DRG编码"),
    ("Payment_Typology_1", "主要支付方"),
]
for f, label in fk_fields:
    cur.execute(f"SELECT COUNT(*) FROM medical_data WHERE `{f}` IS NULL")
    c = cur.fetchone()[0]
    report(f"{label}({f}) IS NULL", c)

# ---------- 总结 ----------
print("\n" + "=" * 65)
if issues_found == 0:
    print("🎉 体检通过！数据完全干净，可以放心交付。")
else:
    print(f"⚠️  共发现 {issues_found} 项异常，请检查上面的 ⚠️ 标记项")
print("=" * 65)

conn.close()