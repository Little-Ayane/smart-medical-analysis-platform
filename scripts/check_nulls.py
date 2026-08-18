import pymysql

DB = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "Csu@Boy727620zy",      # ← 这行改成你自己的 MySQL 密码！
    "database": "medical_db",
    "charset": "utf8mb4"
}

conn = pymysql.connect(**DB)
cur = conn.cursor()

# 查所有字段
cur.execute("DESCRIBE medical_data")
columns = [row[0] for row in cur.fetchall()]

print("=" * 60)
print("medical_data 空值排查")
print("=" * 60)

total_nulls = 0
for col in columns:
    # 查 NULL
    cur.execute(f"SELECT COUNT(*) FROM medical_data WHERE `{col}` IS NULL")
    null_count = cur.fetchone()[0]

    # 查空字符串
    cur.execute(f"SELECT COUNT(*) FROM medical_data WHERE TRIM(COALESCE(`{col}`, '')) = ''")
    empty_count = cur.fetchone()[0]

    # 查 'nan' 字符串
    cur.execute(f"SELECT COUNT(*) FROM medical_data WHERE `{col}` = 'nan'")
    nan_count = cur.fetchone()[0]

    total = null_count + empty_count + nan_count
    if total > 0:
        print(f"  ⚠️  {col}:")
        print(f"      NULL={null_count}, 空字符串={empty_count}, 'nan'={nan_count}")
        total_nulls += total
    else:
        print(f"  ✅ {col}: 无空值")

print("=" * 60)
print(f"空值总计: {total_nulls} 条")

# 单独看性别分布
print("\n--- 性别分布 ---")
cur.execute("SELECT Gender, COUNT(*) FROM medical_data GROUP BY Gender")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]}")

conn.close()
print("\n✅ 排查完成")