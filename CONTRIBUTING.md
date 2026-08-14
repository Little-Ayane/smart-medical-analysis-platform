# 团队协作规范（CONTRIBUTING）

> 智慧医疗大数据与AI大模型分析平台 —— 5 人团队 Git 协作约定。
> 本文件是团队提交代码的唯一规范来源，所有人（含组长）都必须遵守。

---

## 一、角色与分支分工

| 成员 | 职责 | 负责分支 |
| --- | --- | --- |
| **P1** 项目负责人/架构师 | 架构设计、数据库、集成测试、review 合并 | `main`（维护）+ `docs/`、`chore/` 分支 |
| **P2** 数据预处理工程师 | 数据清洗、标准化、入库 | `feature/P2` |
| **P3** 分析服务工程师 | 聚合分析、Flask API | `feature/P3` |
| **P4** AI 交互工程师 | LangChain Agent、意图识别 | `feature/P4` |
| **P5** 前端工程师 | Vue 界面、ECharts 图表 | `feature/P5` |

**核心原则：`main` 永远是能跑起来的稳定版，任何人的代码都不能直接 push 到 `main`，必须走 Pull Request。**

---

## 二、分支命名规范

| 前缀 | 用途 | 示例 |
| --- | --- | --- |
| `feature/Px` | 各模块功能开发 | `feature/P2`、`feature/P3` |
| `fix/` | 修复 bug | `fix/P3-api-500` |
| `docs/` | 文档变更 | `docs/api-contract` |
| `chore/` | 构建、配置、环境 | `chore/db-schema` |

命名用小写英文 + 短横线，不要用中文和空格。

---

## 三、标准工作流程（每个人都要走）

```bash
# ① 克隆仓库（首次）
git clone git@github.com:Little-Ayane/smart-medical-analysis-platform.git
cd smart-medical-analysis-platform

# ② 搭建本地环境（只做一次，不要提交 .venv）
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# ③ 每次开工前，先同步最新 main
git checkout main
git pull origin main

# ④ 从最新的 main 创建/切回自己的分支
git checkout -b feature/P2          # 首次
git checkout feature/P2 && git merge main   # 已存在则并入最新 main

# ⑤ 开发 + 频繁小步提交
git add -A
git commit -m "feat(P2): 完成分块读取 TSV 模块"
git push -u origin feature/P2
```

**完成一个功能后：** 到 GitHub 仓库点 **Pull Request** → 选 `feature/P2` 合并到 `main` → 指定 P1 为 reviewer → 写清楚改动说明。

---

## 四、提交信息规范（Conventional Commits）

格式：`类型(模块): 一句话说明`

| 类型 | 含义 | 示例 |
| --- | --- | --- |
| `feat` | 新功能 | `feat(P2): 完成缺失值处理` |
| `fix` | 修 bug | `fix(P3): 修复聚合接口年份过滤` |
| `docs` | 文档 | `docs: 更新接口文档` |
| `refactor` | 重构（不改功能） | `refactor(P4): 抽离意图解析函数` |
| `chore` | 杂项/配置 | `chore: 初始化建库脚本` |
| `test` | 测试 | `test(P3): 补充聚合接口单测` |

规则：一句话说清楚「做了什么」，不超过 50 字，中文或英文皆可，团队统一即可。

---

## 五、Pull Request 规范

1. **一个 PR 只做一件事**：一个功能/一个 bug，不要混着改。
2. **标题**：和 commit 风格一致，如 `feat(P2): 完成数据入库模块`。
3. **描述**：写清楚「改了什么 / 为什么 / 怎么验证」。
4. **指定 reviewer**：默认指定 P1（组长）review，跨模块改动指定相关成员。
5. **合并方式**：小改动用 `Squash and merge`（历史干净），大功能用 `Merge commit`（保留过程）。
6. **合并后**：删除远程分支，本地切回 `main` 并 `git pull`。

---

## 六、冲突处理

1. 合并前先 `git checkout main && git pull`，再 `git checkout feature/Px && git merge main`，本地先解决冲突。
2. 冲突标记 `<<<<<<<` / `=======` / `>>>>>>>` 必须全部处理干净。
3. 拿不准的冲突，在群里截图讨论，不要硬合并覆盖别人代码。

---

## 七、代码与环境约定

- **环境**：统一 Python 3.11，依赖用 `requirements.txt` 管理，`pip install -r requirements.txt` 安装。
- **不要提交**：`.venv/`、`__pycache__/`、原始数据集（`data/*.tsv` 等，已在 `.gitignore` 排除）。
- **数据库密码**：本地用默认空密码即可，不要把真实密码写进代码提交。
- **代码风格**：注释完整、命名规范，函数写 docstring，参照现有 `preprocess.py` / `app.py` 的写法。

---

## 八、常用命令速查

```bash
git status                     # 看当前状态
git checkout main && git pull  # 同步最新 main
git checkout -b feature/P3     # 新建分支
git add -A && git commit -m "feat(P3): xxx"   # 提交
git push -u origin feature/P3  # 推送到远程
git log --oneline -5           # 看最近提交
```

---

**一句话总结**：**开发在自己的 `feature/Px` 分支，合并一律走 PR 让组长 review，`main` 保持稳定可运行。**
