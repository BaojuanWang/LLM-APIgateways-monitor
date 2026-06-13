#!/bin/bash
# 流水线入口
# 用法（本地手动）: bash scripts/run_pipeline.sh
# 用法（定时）: crontab -e
#   0 * * * * cd /你的项目路径 && bash scripts/run_pipeline.sh >> scripts/pipeline.log 2>&1

cd "$(dirname "$0")/.."

echo ""
echo "=========================================="
echo "$(date '+%Y-%m-%d %H:%M:%S') 开始运行流水线"
echo "=========================================="

echo "[Step 1] 抓取hvoy平台列表..."
python3 scripts/hvoy_tracker.py

echo ""
echo "[Step 2] 检测平台在线状态..."
python3 scripts/pipeline.py

echo ""
echo "$(date '+%Y-%m-%d %H:%M:%S') 流水线完成"
