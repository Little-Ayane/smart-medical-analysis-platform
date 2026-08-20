# 核心分析功能模块

## 模块简介

本模块提供医疗数据的核心分析功能，支持多维度数据探索和交互式查询。

## 功能列表

| 功能 | 说明 | 接口 |
|------|------|------|
| 维度组合选择 | 自由组合维度进行聚合分析 | `/api/v1/analysis/dimension-combine` |
| 指标切换 | 按指标组切换查看不同指标 | `/api/v1/analysis/metric-switch` |
| 逐级下钻 | 从汇总逐层下钻到明细 | `/api/v1/analysis/drill-down` |
| 时间上卷 | 按年度/季度/月度汇总 | `/api/v1/analysis/time-rollup` |
| 交叉透视 | 行列维度交叉分析 | `/api/v1/analysis/pivot` |

## 聚合结果查询（毫秒级）

| 接口 | 说明 |
|------|------|
| `GET /api/v1/agg/drg/ranking` | DRG费用排名 |
| `GET /api/v1/agg/hospital/stats` | 医院统计 |
| `GET /api/v1/agg/diagnosis/stats` | 诊断统计 |
| `GET /api/v1/agg/mortality/risk` | 死亡风险分布 |
| `GET /api/v1/agg/severity/stats` | 严重程度分布 |
| `GET /api/v1/agg/yearly/trend` | 年度趋势 |
| `GET /api/v1/agg/age/distribution` | 年龄分布 |
| `GET /api/v1/agg/payment/stats` | 支付方式分布 |
| `GET /api/v1/agg/summary` | 数据总览 |

## 启动方式

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量（复制模板后编辑）
cp .env.example .env

# 启动服务
python main.py
```

服务默认运行在 `http://localhost:8000`

## 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `MYSQL_HOST` | MySQL地址 | localhost |
| `MYSQL_PORT` | MySQL端口 | 3306 |
| `MYSQL_USER` | MySQL用户名 | root |
| `MYSQL_PASSWORD` | MySQL密码 | （空） |
| `MYSQL_DATABASE` | 数据库名 | medical_db |
| `HIVE_HOST` | Hive地址 | localhost |
| `HIVE_PORT` | HiveServer2端口 | 10000 |
| `DATA_SOURCE` | 数据源类型 | mysql |

## 技术架构

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   main.py   │───→│  API路由层  │───→│  服务层     │
└─────────────┘    └─────────────┘    └──────┬──────┘
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    ↓                        ↓                        ↓
             ┌─────────────┐         ┌─────────────┐         ┌─────────────┐
             │  MySQL DAO  │         │   Hive DAO  │         │  DAO工厂    │
             └─────────────┘         └─────────────┘         └─────────────┘
```

## 数据源切换

修改环境变量 `DATA_SOURCE`：

```bash
# 使用MySQL（默认，毫秒级响应）
DATA_SOURCE=mysql

# 使用Hive（离线分析）
DATA_SOURCE=hive
```

## ETL同步

预聚合结果表提供毫秒级查询响应：

```bash
# 手动执行ETL同步
bash etl_sync.sh

# 定时任务（每天凌晨2点）
# crontab -e
# 0 2 * * * cd /path/to/核心功能 && bash etl_sync.sh >> /tmp/etl.log 2>&1
```
