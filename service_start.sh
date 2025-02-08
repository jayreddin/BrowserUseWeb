#!/bin/bash

# 既存の仮想環境をdeactivate
deactivate 2>/dev/null || true

# 新しい仮想環境をactivate
source .venv/bin/activate

# Ubuntu環境の場合のみsysctlを実行
if grep -q "Ubuntu" /etc/os-release; then
  if [ $(sysctl -n kernel.apparmor_restrict_unprivileged_unconfined) != "0" ]; then
    sudo sysctl -w kernel.apparmor_restrict_unprivileged_unconfined=0
  fi
  if [ $(sysctl -n kernel.apparmor_restrict_unprivileged_userns) != "0" ]; then
    sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
  fi
fi

# logsディレクトリ作成（存在しない場合）
mkdir -p logs

# 現在の日付でログファイル名を生成
log_file="logs/log_$(date +%Y_%m_%d).log"

# アプリケーション実行とログ出力
script -afq -c "./app.py" "$log_file"
