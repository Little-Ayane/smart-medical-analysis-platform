#!/bin/bash
# WSL启动时自动运行的服务启动脚本
# 由 /etc/wsl.conf [boot] command 调用
LOG=/var/log/wsl-boot.log
exec >> $LOG 2>&1
echo "=== $(date) boot_services start ==="

# 1. SSH
service ssh start
sleep 1

# 2. MySQL
service mysql start
sleep 3

# 3. Hadoop (以luo用户启动)
source /etc/profile.d/hadoop-env.sh
export HDFS_NAMENODE_USER=luo HDFS_DATANODE_USER=luo HDFS_SECONDARYNAMENODE_USER=luo
export YARN_RESOURCEMANAGER_USER=luo YARN_NODEMANAGER_USER=luo

# 检查是否已运行，避免重复启动
if ! pgrep -f "proc_namenode" > /dev/null 2>&1; then
    su - luo -c "source /etc/profile.d/hadoop-env.sh; export HDFS_NAMENODE_USER=luo HDFS_DATANODE_USER=luo HDFS_SECONDARYNAMENODE_USER=luo YARN_RESOURCEMANAGER_USER=luo YARN_NODEMANAGER_USER=luo; /opt/hadoop/sbin/start-dfs.sh; /opt/hadoop/sbin/start-yarn.sh" 2>&1
    sleep 5
fi

# 4. Hive Metastore
if ! pgrep -f "HiveMetaStore" > /dev/null 2>&1; then
    su - luo -c "source /etc/profile.d/hadoop-env.sh; mkdir -p /data/hive/logs; nohup /opt/hive/bin/hive --service metastore > /data/hive/logs/metastore.log 2>&1 &"
    sleep 20
fi

# 5. HiveServer2
if ! pgrep -f "HiveServer2" > /dev/null 2>&1; then
    su - luo -c "source /etc/profile.d/hadoop-env.sh; nohup /opt/hive/bin/hive --service hiveserver2 > /data/hive/logs/hiveserver2.log 2>&1 &"
    sleep 25
fi

echo "=== $(date) boot_services done ==="
echo "--- jps ---"
su - luo -c "source /etc/profile.d/hadoop-env.sh; jps" 2>&1
