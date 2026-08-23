# Hive远程连接指南（队友使用）

> 队友使用：通过 **Windows局域网IP** 连接 Hive 数仓，无需自己部署环境。
> 前提：提供方电脑开机 + WSL 服务运行 + 已运行《配置Hive远程共享.bat》

---

## 一、连接信息

| 项目 | 值 |
|------|-----|
| JDBC地址 | `jdbc:hive2://192.168.1.22:10000/default` |
| 用户名 | `luo` |
| 密码 | （无，HiveServer2 未启用认证） |
| HDFS Web UI | http://192.168.1.22:9870 |
| YARN Web UI | http://192.168.1.22:8088 |

> ⚠️ IP `192.168.1.22` 为示例，实际以提供方电脑当前局域网IP为准
> （Windows设置 → 网络 → WLAN → 查看IP；或命令行 `ipconfig`）

---

## 二、方式1：Hive CLI / Beeline 查询

队友机器需安装 Hadoop 或 Hive 客户端（或直接用 Python）。

**方式A - Beeline（需本地有Hive/beeline）**
```bash
beeline -u "jdbc:hive2://192.168.1.22:10000/default" -n luo
# 进入后执行
SHOW DATABASES;            -- 应看到 ods / dwd / dws / ads
USE dws; SELECT * FROM dws_yearly_stats;
```

**方式B - Python (pyhive) 推荐**
```bash
pip install pyhive[hive] thrift sasl
```

```python
from pyhive import hive
conn = hive.connect(host="192.168.1.22", port=10000, username="luo", database="default")
cur = conn.cursor()
cur.execute("SELECT discharge_year, discharge_count, total_costs FROM dws.dws_yearly_stats ORDER BY discharge_year")
for row in cur.fetchall():
    print(row)
```

**方式C - Python (JDBC via JayDeBeApi)**
```bash
pip install jaydebeapi
```
（需要JDBC驱动，较复杂，推荐方式B）

---

## 三、数仓表结构速查

| 库 | 表 | 说明 | 行数 |
|----|-----|------|------|
| ods | ods_medical_data | 原始宽表34列 | 10,378,775 |
| dwd | dwd_discharge_detail | 清洗明细+派生字段 | 10,378,775 |
| dws | dws_discharge_summary | 多维聚合 | 33,445 |
| dws | dws_yearly_stats | 年度统计 | 5 |
| ads | ads_yearly_overview | 年度总览+环比 | 5 |
| ads | ads_hospital_area_stats | 医院服务区 | ~25 |
| ads | ads_diagnosis_analysis | 疾病分类TOP | ~300 |
| ads | ads_patient_profile | 患者画像 | ~50 |

---

## 四、常用分析SQL示例

```sql
-- 1. 年度费用趋势
SELECT discharge_year, discharge_count, ROUND(total_costs/1e9,2) AS cost_billions
FROM ads.ads_yearly_overview ORDER BY discharge_year;

-- 2. 2024年各医院服务区成本占比
SELECT hospital_service_area, discharge_count, avg_costs, cost_share
FROM ads.ads_hospital_area_stats WHERE discharge_year=2024
ORDER BY total_costs DESC;

-- 3. 疾病TOP10（循环系统）
SELECT apr_mdc_description, discharge_count, ROUND(total_costs/1e9,2) AS cost_billions
FROM ads.ads_diagnosis_analysis WHERE discharge_year=2024
ORDER BY discharge_count DESC LIMIT 10;

-- 4. 患者画像（年龄×性别）
SELECT age_group, gender, discharge_count, avg_costs, patient_share
FROM ads.ads_patient_profile WHERE discharge_year=2024
ORDER BY discharge_count DESC;
```

---

## 五、常见问题

| 问题 | 解决 |
|------|------|
| 连接超时 | ① 确认提供方电脑已运行《配置Hive远程共享.bat》② 确认双方在同一局域网 |
| 端口10000不通 | 检查提供方防火墙是否放行（bat脚本已处理） |
| WSL重启后连接失败 | 提供方重新运行 bat 脚本（WSL的IP可能变化） |
| 查询很慢 | Hive底层是MapReduce，全表扫描数分钟属正常，建议多用DWS/ADS汇总表 |
