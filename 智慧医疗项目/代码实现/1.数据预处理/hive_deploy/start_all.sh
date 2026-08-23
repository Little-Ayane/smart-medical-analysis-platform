#!/bin/bash
# 全量启动: SSH → MySQL → HDFS → YARN → MetaStore → HiveServer2
# 可重复执行，已启动的会跳过
set +e

echo "========== 1. 启动 SSH =========="
service ssh start 2>/dev/null || true
sleep 1
pgrep -x sshd > /dev/null && echo "  sshd: OK" || echo "  sshd: FAIL"

echo ""
echo "========== 2. 启动 MySQL =========="
service mysql start 2>/dev/null || /etc/init.d/mysql start 2>/dev/null || true
sleep 2
if pgrep -x mysqld > /dev/null; then
    echo "  mysqld: OK"
else
    echo "  mysqld: FAIL - 尝试mysqld_safe"
    mysqld_safe --user=mysql &
    sleep 5
fi

echo ""
echo "========== 3. 启动 HDFS =========="
source /etc/profile.d/hadoop-env.sh
export HDFS_NAMENODE_USER=luo HDFS_DATANODE_USER=luo HDFS_SECONDARYNAMENODE_USER=luo
export YARN_RESOURCEMANAGER_USER=luo YARN_NODEMANAGER_USER=luo

# 检查NameNode是否已运行
if pgrep -f "proc_namenode" > /dev/null; then
    echo "  NameNode 已运行，跳过"
else
    su - luo -c "source /etc/profile.d/hadoop-env.sh; export HDFS_NAMENODE_USER=luo HDFS_DATANODE_USER=luo HDFS_SECONDARYNAMENODE_USER=luo; $HADOOP_HOME/sbin/start-dfs.sh" 2>&1 | grep -E 'Starting|ERROR' | head -5
    sleep 5
fi

echo ""
echo "========== 4. 启动 YARN =========="
if pgrep -f "proc_resourcemanager" > /dev/null; then
    echo "  ResourceManager 已运行，跳过"
else
    su - luo -c "source /etc/profile.d/hadoop-env.sh; export YARN_RESOURCEMANAGER_USER=luo YARN_NODEMANAGER_USER=luo; $HADOOP_HOME/sbin/start-yarn.sh" 2>&1 | grep -E 'Starting|ERROR' | head -5
    sleep 5
fi

echo ""
echo "========== 5. 端口检查 (Hadoop层) =========="
for port in 9870 9864 8088 8042; do
    (echo > /dev/tcp/127.0.0.1/$port) 2>/dev/null && echo "  Port $port LISTEN OK" || echo "  Port $port DOWN"
done

echo ""
echo "========== 6. 启动 Hive MetaStore =========="
if pgrep -f "HiveMetaStore" > /dev/null || (echo > /dev/tcp/127.0.0.1/9083) 2>/dev/null; then
    echo "  MetaStore 已运行"
else
    su - luo -c "
source /etc/profile.d/hadoop-env.sh
export HADOOP_HOME=/opt/hadoop HIVE_HOME=/opt/hive
mkdir -p /data/hive/logs
cd \$HIVE_HOME
nohup bin/hive --service metastore > /data/hive/logs/metastore.log 2>&1 &
echo \$!
" 2>/dev/null
    echo "  等MetaStore启动(30秒)..."
    sleep 30
fi

echo ""
echo "========== 7. 启动 HiveServer2 =========="
if pgrep -f "HiveServer2" > /dev/null || (echo > /dev/tcp/127.0.0.1/10000) 2>/dev/null; then
    echo "  HiveServer2 已运行"
else
    su - luo -c "
source /etc/profile.d/hadoop-env.sh
export HADOOP_HOME=/opt/hadoop HIVE_HOME=/opt/hive
cd \$HIVE_HOME
nohup bin/hive --service hiveserver2 > /data/hive/logs/hiveserver2.log 2>&1 &
echo \$!
" 2>/dev/null
    echo "  等HiveServer2启动(40秒)..."
    sleep 40
fi

echo ""
echo "========== 8. 全端口检查 =========="
for port in 3306 9083 10000 10002 9870 9864 8088 8042; do
    (echo > /dev/tcp/127.0.0.1/$port) 2>/dev/null && echo "  Port $port LISTEN OK" || echo "  Port $port DOWN"
done

echo ""
echo "========== 9. jps 进程列表 =========="
su - luo -c "source /etc/profile.d/hadoop-env.sh; jps" 2>/dev/null

echo ""
echo "========== 10. Beeline 冒烟 =========="
if (echo > /dev/tcp/127.0.0.1/10000) 2>/dev/null; then
    # 等HS2内部初始化完成
    sleep 5
    su - luo -c "
source /etc/profile.d/hadoop-env.sh
cd \$HIVE_HOME
bin/beeline -u jdbc:hive2://localhost:10000/default -n luo -e 'SELECT 1 as ping; SHOW DATABASES;' 2>&1 | grep -vE 'SLF4J|binding|See http|Actual binding|^\s*$' | tail -15
"
    RESULT=$?
    if [ $RESULT -eq 0 ]; then
        echo ""
        echo "=========================================="
        echo "  ALL SERVICES UP! Beeline 连接成功!"
        echo "=========================================="
    else
        echo ""
        echo "[WARN] beeline失败, 查错误日志:"
        grep -iE 'Exception|Error|Caused' /data/hive/logs/hiveserver2.log 2>/dev/null | tail -5
    fi
else
    echo "  HiveServer2 端口10000未监听, 无法测试"
    echo "  MetaStore日志最后10行:"
    tail -10 /data/hive/logs/metastore.log 2>/dev/null
    echo "  HiveServer2日志最后10行:"
    tail -10 /data/hive/logs/hiveserver2.log 2>/dev/null
fi
