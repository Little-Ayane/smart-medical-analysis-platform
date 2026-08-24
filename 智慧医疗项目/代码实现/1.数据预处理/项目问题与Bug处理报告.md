# 项目问题与Bug处理报告

> 项目：智慧医疗大数据与AI大模型分析平台
> 负责模块：数据预处理 + 后端接口开发 + Hive数仓
> 整理人：骆志远    日期：2026-08-24

---

## 一、数据清洗阶段的问题

### 问题1：数据重复插入，数据量翻倍

**现象**：MySQL 中 `medical_data` 表数据量从预期的 800 多万条暴涨到 2000 多万条。

**原因**：数据导入脚本在运行报错后重复执行，且未做幂等保护，导致每次重新运行都会把 CSV 数据再次插入，数据被重复写入。

**处理过程**：
1. 先尝试用 SQL 去重（按主键/业务键），但数据量太大、去重效率低，且部分行无唯一键可依。
2. 最终决定放弃去重，改为 `TRUNCATE TABLE` 清空表，再按 5 个年份（2020-2024）逐年重新导入，从源头保证数据干净。
3. 导入脚本改为支持断点续传（记录已导入批次），避免重复。

**经验**：入库脚本必须设计为幂等（可重复执行），否则一次报错重跑就会污染数据。

---

### 问题2：MySQL 崩溃，锁表溢出（1206 错误）

**现象**：批量 INSERT 长时间运行后，MySQL 报 `Lock wait timeout exceeded` / 锁表溢出，甚至 MySQL 服务崩溃，需要重启服务。

**原因**：长事务持有过多行锁，`innodb_lock_wait_timeout` 超时；且单批插入数据量过大。

**处理过程**：
1. 定位到长时间运行的 INSERT 进程，通过 `SHOW PROCESSLIST` 找到并终止。
2. 由管理员重启 MySQL80 服务恢复。
3. 修改插入策略：**每批 500 行独立 commit**，避免单事务持有过多锁。
4. 效果：速度反而提升（15K/s vs 之前 4K/s），彻底规避锁表问题。

---

### 问题3：dim_drg 维度表唯一键冲突，映射失败

**现象**：星型模型构建时，事实表外键映射大量失败，`dim_drg` 维表出现重复行。

**原因**：`dim_drg` 最初使用 3 列自然键 `(apr_drg_code, apr_mdc_code, apr_severity_code)`，但该组合在 15,554 行中只有 1,814 个唯一值，即大量不同记录被归并到同一键，导致映射失败率 100%。

**处理过程**：
1. 分析数据后发现 3 列键区分度不足。
2. 扩展为 **5 列自然键**：`(apr_drg_code, apr_mdc_code, apr_severity_code, apr_risk_of_mortality, apr_medical_surgical)`。
3. 5 列键产生 5,761 个唯一值，覆盖全部数据，映射失败归零。

**经验**：维度表自然键设计必须考虑业务字段的组合区分度，用数据说话，不能想当然。

---

## 二、Hive/Hadoop 环境部署问题

### 问题4：Hadoop 与 Hive 的 guava 版本冲突

**现象**：Hive 启动时报类加载失败，`NoClassDefFoundError`。

**原因**：Hive 自带的 `guava-19.0.jar` 与 Hadoop 的 `guava-27.0-jre.jar` 版本冲突。

**处理过程**：删除 Hive lib 下的旧 guava，将 Hadoop 的 `guava-27.0-jre.jar` 复制到 Hive lib 目录，统一版本。

---

### 问题5：HiveServer2 连接被重置（Thrift 协议不匹配）

**现象**：beeline 连接 `jdbc:hive2://localhost:10000` 时连接被重置。

**原因**：`hive.server2.authentication` 配置为 `NOSASL` 导致 Thrift 协议版本不匹配。

**处理过程**：修改为 `hive.server2.authentication=NONE`，beeline 无需额外认证参数即可连接。

---

### 问题6：YARN ResourceManager 反复崩溃（SIGHUP）

**现象**：ResourceManager 进程频繁消失，日志显示 `RECEIVED SIGNAL 1: SIGHUP`，导致 MR 任务无法执行。

**原因**：WSL 会话结束时会向会话内启动的进程组发送 SIGHUP 挂断信号，而 ResourceManager 是通过 `start-yarn.sh` 在会话内启动的，因此被连带杀死。

**处理过程**：改用 `setsid` 启动 YARN，使进程脱离会话进程组：
```bash
setsid bash -c "/opt/hadoop/sbin/start-yarn.sh" < /dev/null > /tmp/yarn.log 2>&1 &
```

---

### 问题7：MRAppMaster 类找不到

**现象**：Hive 执行 MapReduce 任务失败，报 `Could not find or load main class org.apache.hadoop.mapreduce.v2.app.MRAppMaster`。

**原因**：`yarn-site.xml` 中缺少 `yarn.application.classpath` 配置，或使用了 `$HADOOP_HOME` 变量但未被展开。

**处理过程**：
1. 在 `yarn-site.xml` 中添加 `yarn.application.classpath`，使用**绝对路径**（`$HADOOP_HOME` 在配置中不会被替换）。
2. 在 `mapred-site.xml` 中设置 `yarn.app.mapreduce.am.env` / `mapreduce.map.env` / `mapreduce.reduce.env` 为 `HADOOP_MAPRED_HOME=/opt/hadoop-3.3.6`。
3. 重启 YARN 和 HiveServer2 使配置生效。

---

### 问题8：sed 修改 XML 导致配置文件损坏

**现象**：用 `sed` 批量修改 `yarn-site.xml` 后，XML 出现孤立 `<property>` 标签，`WstxParsingException` 解析失败，YARN 无法启动。

**原因**：`sed` 的删除/插入操作破坏了 XML 标签配对结构。

**处理过程**：用 Python 完整重写 XML 文件，并用 `xml.dom.minidom.parse()` 验证格式合法后再启动服务。

**经验**：修改 XML 配置文件不要用 sed 拼接，直接重写完整文件最稳妥。

---

### 问题9：Hive 查询返回 NULL（UTF-16 编码问题）

**现象**：数据成功导入 Hive 后，`SELECT` 查询所有字段返回 NULL，但 HDFS 文件大小正常。

**原因**：从 Windows 导出的 TSV 文件是 **UTF-16 LE 编码**（BOM 为 FF FE），而 Hive 期望 UTF-8 编码，导致解析失败。

**处理过程**：
1. 用 `xxd`/`od -c` 检查文件头，确认 BOM 为 UTF-16。
2. 使用 `iconv -f UTF-16 -t UTF-8` 转换编码，去除 BOM，重新上传 HDFS。
3. 转换后数据查询正常，COUNT = 10,378,775 与源一致。

---

### 问题10：WSL 服务开机不自启 / 会话结束进程被杀

**现象**：每次 WSL 重启后 Hadoop/Hive 服务需要手动启动，且会话结束后进程被终止。

**处理过程**：
1. 编写 `boot_services.sh` 启动脚本，通过 `/etc/wsl.conf` 的 `[boot] command` 配置开机自启。
2. 配置 `.wslconfig` 添加 `vmIdleTimeout=-1` 防止 VM 空闲自动关闭。

---

## 三、Git 与代码运行问题

### 问题11：`git: 'remote-https' is not a git command`

**现象**：`git push` 报 `git: 'remote-https' is not a git command`。

**原因**：Git 安装缺少 `git-remote-https.exe`（在 `D:\Git\mingw64\libexec\git-core` 目录）。

**处理过程**：复制 `git-remote-ftp.exe` 并重命名为 `git-remote-https.exe` 解决。

---

### 问题12：GitHub 推送被拒（remote contains work）

**现象**：`git push` 报 `Updates were rejected because the remote contains work that you do not have locally`。

**原因**：远端 main 分支有本地没有的提交（队友推送过）。

**处理过程**：执行 `git pull --rebase origin main` 合并远端提交后重新推送。

---

### 问题13：GitHub 无法连接（hosts 被劫持）

**现象**：`github.com:443` 无法连接，`ping github.com` 解析到 127.0.0.1。

**原因**：hosts 文件被工具批量修改，将 github.com 等域名指向 127.0.0.1。

**处理过程**：备份 hosts 文件，注释掉 GitHub 相关条目后恢复网络。

---

### 问题14：medical_data_pipeline.py 无法运行（ModuleNotFoundError）

**现象**：运行 `medical_data_pipeline.py` 报 `ModuleNotFoundError: No module named 'scripts'`。

**原因**：第 43 行残留了一行无效导入 `from scripts.check_nulls import total`，`scripts` 不是可导入的包。

**处理过程**：
1. 删除无效 import。
2. 进一步排查发现第 694 行存在真正的 bug：使用了未定义的变量 `total`，而正确变量名为 `total_rows`。修复为 `total_rows` 后程序正常运行。

**经验**：报错只是表象，删除错误 import 后还要检查相关变量是否真的被正确引用。

---

## 四、环境与资源问题

### 问题15：D 盘空间不足（仅剩 3GB）

**现象**：Hive 数据迁移过程中 D 盘剩余空间骤降至 3GB，面临爆盘风险。

**处理过程**：
1. 扫描 D 盘顶层大目录，识别无关文件。
2. 清理与环境软件无关的文件：WSL 导出包（3.97GB）、星型导出目录（1.91GB）、旧 SQL 备份（1.86GB）、原始 CSV（3.53GB），释放约 33GB。
3. 清空回收站，回收站占用 11.27GB 也需手动清空。

**经验**：WSL 虚拟磁盘 `ext4.vhdx` 会随写入膨胀，需定期 compact 压缩。

---

### 问题16：VMware 无法创建虚拟机

**现象**：VMware 创建虚拟机失败，提示无法打开配置文件，拒绝访问。

**处理过程**：放弃 VMware，改用 WSL2 部署 Hadoop/Hive 环境，配置 `.wslconfig` 限制内存 8GB、处理器 4 核。

---

## 五、Bug 处理总结

| 类别 | 问题数 | 典型根因 | 通用解决思路 |
|------|--------|---------|-------------|
| 数据清洗 | 3 | 脚本非幂等、锁表、键设计不合理 | 幂等设计、小批量提交、用数据验证键区分度 |
| 环境部署 | 7 | 依赖冲突、协议不匹配、会话信号 | 版本统一、配置核对、进程隔离(setsid) |
| Git/代码 | 4 | 环境缺失、残留导入、变量笔误 | 排查环境、删除冗余、核对变量作用域 |
| 资源管理 | 2 | 磁盘膨胀、虚拟化方案 | 定期清理、合理选型 |

---

## 六、经验与教训

1. **数据入库必须幂等**：脚本要能安全重跑，否则一次报错重跑就会造成数据污染。
2. **大数据写入用小批量**：每批 500 行独立提交，比大事务更快更稳。
3. **维度表自然键要用数据验证**：不能拍脑袋定列，要通过唯一性统计确认。
4. **WSL 下服务进程要 setsid 隔离**：避免会话结束 SIGHUP 杀死后台服务。
5. **XML 配置修改要整体重写**：sed 拼接易破坏结构，改完必须验证格式。
6. **排查 Bug 要追根因**：报错只是表象，比如 import 报错背后其实是变量名笔误。

---

*报告结束*
