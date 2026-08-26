# 智慧医疗大数据与 AI 大模型分析平台

基于 **Vue3 + ECharts + Flask/FastAPI + MySQL** 的医疗数据分析平台，覆盖成本、病种、支付、质量、急诊、DRG 等维度，并内置 AI 大模型智能问答助手。数据规模 **1038 万行住院记录（2020–2024）**，前端图表已做持久化预聚合优化，秒级加载。

## 功能模块

- **数据大屏（Dashboard / 3D 大屏）**：六维图表总览 + WebGL 3D 地图大屏
- **成本分析**：费用成本差 / 利润率 / 效率评级 / 费用构成 / 趋势
- **病种分析**：TOP 诊断 / 手术、严重程度构成、人群差异、年龄金字塔、地区差异、热力图
- **支付分析**：支付结构、交叉、桑基图、费用关系、自付负担、汇总
- **质量监测**：KPI 总览、死亡率排行、住院日排行、医院质量对比、离院去向
- **急诊分析**：急诊率趋势、急诊对比、平均住院日、超标识别、转归交叉
- **DRG 分析**：费用排名、住院天数对比、死亡风险、CMI 排名、离群识别
- **AI 智能问答**：自然语言提问，自动路由到对应分析端点并生成图表/报告

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 · Vue Router · ECharts / echarts-gl · Vite · Axios |
| 后端 | Flask（P3 分析）· FastAPI（core / DRG）· PyMySQL |
| 数据 | MySQL 8.0 · 星型模型（fact_discharge + 7 维度表） |
| AI | 大模型（OpenAI 兼容接口）· 工具调用 / function-calling |

## 架构与端口

```
前端 Vite (5173) ──代理──> Flask 分析服务 P3 (5000)   # 病种/支付/质量/成本/急诊
                       ├──> FastAPI 核心分析  (8000)   # 动态下钻 / 元数据
                       ├──> FastAPI DRG 分析  (8001)   # DRG 分析
                       └──> AI agent P4       (5001)   # 智能问答
```

| 服务 | 端口 | 启动命令（见 `start.sh`） |
|---|---|---|
| Flask 分析服务 P3 | 5000 | `python3.11 app.py` |
| FastAPI 核心分析 | 8000 | `uvicorn modules.core.main:app --port 8000` |
| FastAPI DRG 分析 | 8001 | `uvicorn modules.drg.main:app --port 8001` |
| AI 交互 agent P4 | 5001 | `python3.11 agent.py` |
| 前端 Vite | 5173 | `npm run dev` |

## 目录结构

```
├── start.sh / stop.sh / open.sh   # 一键启停 + 访问地址
├── backend/
│   ├── requirements.txt           # 后端统一依赖
│   ├── README.md / DATABASE.md    # 后端说明 / 数据库设计
│   └── 智慧医疗项目/
│       ├── 代码实现/
│       │   ├── 1.数据预处理/       # 数据 ETL
│       │   ├── 2.分析服务/         # P3 Flask + core/drg FastAPI + 各分析模块
│       │   └── 3.AI交互/           # P4 AI agent + .env.example 模板
│       └── 接口文档/               # 接口契约文档
├── frontend/
│   └── medical-frontend/          # Vue3 前端（node_modules 需 npm install）
└── database/                      # 建表 / 回填 / 索引 / 预热脚本（含 README）
```

## 快速开始

### 1. 准备数据库

数据库为 MySQL 8.0（本机 `/opt/mysql`，socket `/opt/mysql/mysql.sock`，root 空密码）。
若需从零重建，见 [`database/README.md`](database/README.md) 的脚本执行顺序。

### 2. 安装依赖

```bash
# 后端
pip install -r backend/requirements.txt

# 前端
cd frontend/medical-frontend && npm install && cd ../..
```

### 3. 配置环境变量（AI agent 需要）

```bash
cp backend/智慧医疗项目/代码实现/3.AI交互/.env.example \
   backend/智慧医疗项目/代码实现/3.AI交互/.env
# 编辑 .env，填入 LLM_API_KEY / LLM_BASE_URL 等
```

### 4. 启动

```bash
bash start.sh     # 一键启动全部服务（含后台缓存预热）
bash open.sh      # 查看访问地址
bash stop.sh      # 停止全部服务
```

前端访问 `http://localhost:5173`；core/drg 接口文档分别在 `:8000/docs`、`:8001/docs`。

## 数据库

| 库 | 表 | 规模 |
|---|---|---|
| `medical_db` | fact_discharge + 7 维度表 | 10,378,775 行（2020–2024） |
| `smart_health` | fact_inpatient_discharge + 4 维度表 | 约 200 万行（2021，旧库） |

> 事实表数据 dump（约 977MB）未随仓库提交（live 库已含数据），见 `database/README.md`。

## 性能优化（要点）

针对 16.5GB 大表的图表查询做了持久化预聚合优化，冷查询从 10~130s 降到秒级：

- **持久化预聚合层** `medical_db.api_cache`：结果落盘 MySQL，跨重启存活，不依赖 Redis；
  由 `start.sh` 后台自动预热（`WARM_CACHE=0` 可跳过）。
- **覆盖索引**：为含 `length_of_stay` 的聚合补宽覆盖索引，避免千万次主键回表。
- **反规范化**：把维度列回填到事实表，消除大表 JOIN。
- **DRG 两级聚合**：先按外键 GROUP BY，再 JOIN 小维度表取名。

详细脚本与踩坑记录见 [`database/README.md`](database/README.md)。

### 缓存失效

数据为 2020–2024 静态快照，缓存不过期。重新导入数据后：

```bash
/opt/mysql/bin/mysql --socket=/opt/mysql/mysql.sock -u root medical_db -e "TRUNCATE api_cache;"
python3.11 database/warm_cache.py
```

## 安全说明

- 所有真实密钥（`LLM_API_KEY` 等）仅在本地 `.env` / `.env.production` 中，**已通过
  `.gitignore` 排除**，仓库只提供 `.env.example` 模板。
- `node_modules/`、`__pycache__/`、日志、大 dump 等均不入库。

## License

教育 / 课程项目，保留所有权利。
