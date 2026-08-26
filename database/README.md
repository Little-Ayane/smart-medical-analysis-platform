# database/ — 数据库脚本说明

本目录存放建表、反规范化回填、覆盖索引与缓存预热脚本，按「数据重建顺序」组织。

> 说明：事实表数据 dump（`fact_discharge.sql`，约 977MB、1038 万行）未随仓库提交，
> 因 live 库已含数据。若需从零重建，先按下方顺序导入事实表数据。

## 脚本清单与用途

| 文件 | 用途 |
|---|---|
| `dims.sql` | 7 张维度表建表语句（dim_patient / dim_drg / dim_payment / dim_diagnosis / dim_hospital / dim_procedure / dim_time） |
| `backfill_denorm.sql` | 把维度列反规范化回填到 `fact_discharge`（age_group / gender / race / discharge_year / apr_severity_* / payment_typology_1~3 等 11 列），消除对维度表的 JOIN |
| `backfill_payment.py` | 按外键分批回填支付方式列（`payment_typology_1/2/3`），避免大表单条 UPDATE 锁表 |
| `backfill_hospital.py` | 回填医院 3 列（facility_name / hospital_service_area / hospital_county） |
| `add_denorm_indexes.sql` | 为反规范化列补索引（维度组合覆盖索引，供下钻查询） |
| `add_cache_indexes.sql` | 图表端点覆盖索引（含 `length_of_stay` 的宽索引，避免千万次主键回表） |
| `warm_cache.py` | 图表端点缓存预热脚本：打一遍前端实际请求的参数组合，结果落盘 `medical_db.api_cache`（跨重启持久化，不依赖 Redis） |

## 推荐执行顺序（从零重建）

```bash
MYSQL="/opt/mysql/bin/mysql --socket=/opt/mysql/mysql.sock -u root medical_db"

# 1. 建维度表
$MYSQL < dims.sql

# 2. 导入事实表数据（外部 dump，未随仓库提交）

# 3. 反规范化回填（消除维度表 JOIN）
$MYSQL < backfill_denorm.sql
python3.11 backfill_payment.py
python3.11 backfill_hospital.py

# 4. 建索引（覆盖索引）
$MYSQL < add_denorm_indexes.sql
$MYSQL < add_cache_indexes.sql

# 5. 刷新统计信息（否则优化器选错索引）
$MYSQL -e "ANALYZE TABLE fact_discharge;"

# 6. 预热图表缓存（服务启动后执行）
python3.11 warm_cache.py
```

## 性能优化要点（踩坑记录）

- **覆盖索引**：16.5GB 大表上，聚合查询若无法走覆盖索引会退化成千万次主键回表
  （单条 GROUP BY 曾 6~10 分钟）。解法是显式 `FORCE INDEX` 走含聚合列的覆盖索引。
- **年份谓词**：`idx_year_*` 索引族都以 `discharge_year` 打头，查询不带年份条件时
  优化器无法使用；补 `discharge_year IS NOT NULL`（全集谓词）即可解锁，秒级。
- **DRG 两级聚合**：`dim_drg` 是退化维度（5761 行但仅 336 个 `apr_drg_code`），
  必须「先按外键 GROUP BY → JOIN 维度表 → 外层再按维度列汇总」，且均值用
  `SUM(x)/SUM(cases)` 加权（`AVG(AVG())` 会算错）。
- **建索引后必须 `ANALYZE TABLE`**：否则统计信息过时，优化器选错索引
  （count 查询曾 8s → ANALYZE 后 0.5s）。
- **大表回填分批**：不要单条 `UPDATE ... JOIN`，按外键分批（~10000 行/秒）。

## 缓存失效

数据是 2020–2024 静态快照，`api_cache` 不过期。若重新导入数据：

```bash
$MYSQL -e "TRUNCATE api_cache;"
python3.11 warm_cache.py
```
