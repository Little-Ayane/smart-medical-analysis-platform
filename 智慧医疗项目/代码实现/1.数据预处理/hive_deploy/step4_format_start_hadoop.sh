#!/usr/bin/env bash
# Step4: 格式化NameNode + 启动 HDFS + YARN
# 在 luo 用户下执行
set -e
source /etc/profile.d/hadoop-env.sh 2>/dev/null

export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
export HDFS_NAMENODE_USER=luo
export HDFS_DATANODE_USER=luo
export HDFS_SECONDARYNAMENODE_USER=luo
export YARN_RESOURCEMANAGER_USER=luo
export YARN_NODEMANAGER_USER=luo

echo "==== 1. NameNode 格式化 (一次性) ===="
if [ ! -f /data/hadoop/name/current/VERSION ]; then
    # 清除残留目录
    rm -rf /data/hadoop/{name,data,tmp}/* 2>/dev/null || true
    mkdir -p /data/hadoop/{name,data,tmp}
    chown -R luo:luo /data
    su - luo -c "source /etc/profile.d/hadoop-env.sh; hdfs namenode -format -force -nonInteractive" 2>&1 | tail -5
    echo "  格式化完成"
else
    echo "  NameNode 已格式化，跳过"
fi

echo ""
echo "==== 2. 启动 HDFS (start-dfs.sh) ===="
# Hadoop3 需要设置启动用户为luo以避免权限问题
su - luo -c "
source /etc/profile.d/hadoop-env.sh
export HDFS_NAMENODE_USER=luo HDFS_DATANODE_USER=luo HDFS_SECONDARYNAMENODE_USER=luo
bash $HADOOP_HOME/sbin/start-dfs.sh
" 2>&1 | tail -15
sleep 3

echo ""
echo "==== 3. 启动 YARN (start-yarn.sh) ===="
su - luo -c "
source /etc/profile.d/hadoop-env.sh
export YARN_RESOURCEMANAGER_USER=luo YARN_NODEMANAGER_USER=luo
bash $HADOOP_HOME/sbin/start-yarn.sh
" 2>&1 | tail -10
sleep 3

echo ""
echo "==== 4. jps 检查 5个守护进程 ===="
su - luo -c "source /etc/profile.d/hadoop-env.sh; jps | grep -E 'NameNode|DataNode|SecondaryNameNode|ResourceManager|NodeManager' || jps"
echo ""
echo "==== 5. 各端口存活检查 ===="
for port in 9870 9864 9000 8088 8042; do
    if (echo > /dev/tcp/127.0.0.1/$port) 2>/dev/null; then
        echo "  Port $port :  LISTEN OK"
    else
        echo "  Port $port :  NOT LISTENING"
    fi
done
echo ""
echo "==== 6. 创建HDFS用户目录 + test ===="
su - luo -c "
source /etc/profile.d/hadoop-env.sh
hdfs dfs -mkdir -p /user/luo /user/hive /tmp /warehouse
hdfs dfs -chmod 777 /user /user/luo /user/hive /tmp /warehouse
hdfs dfs -ls /
echo ''
echo '写测试:'
echo 'hello-hadoop' | hdfs dfs -put - /tmp/test.txt 2>/dev/null && hdfs dfs -cat /tmp/test.txt && hdfs dfs -rm -f /tmp/test.txt 2>/dev/null
" 2>&1 | tail -12
echo ""
echo "[DONE] step4 HDFS+YARN启动完成"
