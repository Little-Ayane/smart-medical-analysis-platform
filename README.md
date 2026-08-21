# 智慧医疗大数据与AI大模型分析平台

基于真实医院住院患者出院数据集（200 万+ 条），构建「大数据处理 + AI 智能交互」的智慧医疗分析平台。覆盖原始数据清洗 → 批量处理 → 存储优化 → 多维价值挖掘 → 可视化展示的完整大数据链路。

## 技术栈

| 层 | 技术 |
|---|---|
| 数据处理 | Python 3.11 / Pandas / NumPy / PyMySQL |
| 分析服务 | Flask（RESTful API）/ Redis（二期缓存） |
| AI 交互 | LangChain / LLM（云端或本地 Qwen、BaiChuan） |
| 前端 | Vue 3 + ECharts |
| 存储 | MySQL 8.0（星型模式，1 事实表 + 4 维度表） |
| 大数据（二期） | Hadoop / Spark 3.5 / Hive |

## 目录结构

```
智慧医疗/
├── README.md
├── requirements.txt
├── .gitignore
├── 智慧医疗大数据与AI大模型分析平台_项目企划书.md / .docx
└── 智慧医疗项目/
    ├── 代码实现/
    │   ├── 1. 数据预处理/   # 数据清洗、标准化、去重、批量入库
    │   ├── 2. 分析服务/     # 多维聚合分析 + RESTful API
    │   ├── 3. AI交互/       # LangChain Agent（意图识别 → 工具调用 → 文本生成）
    │   └── 4. 前端/         # Vue3 + ECharts 可视化
    ├── 接口文档/            # RESTful API 接口文档
    ├── 任务清单/            # 5 人详细任务分工
    ├── 数据库设计/          # schema.sql + ER 图与设计说明
    └── 项目计划/            # 项目计划书 + CMMI/RUP 过程文档模板
```

## 环境搭建

```bash
# 1. Python 3.11（建议 >=3.10, <3.13）
python3.11 -m venv .venv
source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 初始化数据库（MySQL 8.0）
mysql -u root -p < 智慧医疗项目/数据库设计/schema.sql
```

## 运行

```bash
# 数据预处理（需要原始 TSV 数据文件）
python 智慧医疗项目/代码实现/P2_数据预处理/preprocess.py --input data/hospital.tsv --db smart_health

# 分析服务 API
python 智慧医疗项目/代码实现/P3_分析服务/app.py   # http://127.0.0.1:5000

# AI 交互（自测）
python 智慧医疗项目/代码实现/P4_AI交互/agent.py

# 前端：直接用浏览器打开 P5_前端/index.html
```

## 说明

- 原始数据集（200 万+ 条住院记录）未随仓库提交，请按需放置到 `data/` 目录。
- 一期为本地规则/模板兜底，二期接入 LangChain + LLM 与 Redis 缓存（依赖见 `requirements.txt` 注释部分）。
