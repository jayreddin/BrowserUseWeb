#!/bin/bash

# /etc/os-release から OS 情報を取得
# コマンドとパッケージ名のペアを定義
OsType=""
if [ -f /etc/os-release ]; then
  . /etc/os-release
  case "$ID" in
    ubuntu)
      OsType="$ID"
      declare -A cmd_pkg_map=(
        [bwrap]="bubblewrap"
        [Xvnc]="tigervnc-standalone-server"
        [ufw]="ufw"
      )
      declare -A sysparam_map=(
        [kernel.apparmor_restrict_unprivileged_unconfined]="0"
        [kernel.apparmor_restrict_unprivileged_userns]="0"
      )
      ;;
    rhel|rocky|alma|centos|fedora)
      OsType="rhel"
      declare -A cmd_pkg_map=(
        [python3.11]="python3.11"
        [bwrap]="bubblewrap"
        [Xvnc]="tigervnc-server"
        [firewall-cmd]="firewalld"
      )
      declare -A sysparam_map=(
      )
      ;;
    *)
      echo "OS information not found"
      exit 1
      ;;
  esac
fi

echo "OS:$OsType"

# 実行するコマンドを配列に格納
cmds=()
# システムパラメータを確認
for param in "${!sysparam_map[@]}"; do
  target_val="${sysparam_map[$param]}"
  current_val="$(sysctl -n $param 2>/dev/null)"
  if [ "$target_val" != "$current_val" ]; then
    echo "check $param is $current_val invalid"
    cmds+=("sudo sysctl -w ${param}=${target_val}")
  else
    echo "check $param is $current_val OK"
  fi
done

# インストールが必要なパッケージを格納する配列
install_list=()
# 各コマンドの存在を確認
for cmd in "${!cmd_pkg_map[@]}"; do
  if ! command -v "$cmd" &> /dev/null; then
    echo "check $cmd not found"
    install_list+=("${cmd_pkg_map[$cmd]}")
  else
  echo "check $cmd OK"
  fi
done

# インストールが必要なパッケージがある場合、インストールを実行
if [ ${#install_list[@]} -ne 0 ]; then
  if [ "ubuntu" == "$OsType" ]; then
    cmds+=("sudo apt-get install ${install_list[*]}")
  else
    cmds+=("sudo dnf install ${install_list[*]}")
  fi
fi

if [ ${#cmds[@]} -ne 0 ]; then
  # 実行予定のコマンド一覧を表示
  echo "The following commands are about to be executed:"
  for cmd in "${cmds[@]}"; do
    echo " $cmd"
  done
  # ユーザーに確認を求める
  read -p "Do you want to proceed with executing these commands? (y/n): " answer
  if [[ ! "$answer" =~ ^[Yy] ]]; then
    echo "Command execution has been canceled."
    exit 1
  fi
  # 実行ループ
  for cmd in "${cmds[@]}"; do
    echo "Executing: $cmd"
    eval "$cmd"
  done
fi

# 既存の仮想環境をdeactivate
deactivate 2>/dev/null || true

# venvをチェックする
if [ -x .venv/bin/python3.11 -o -x .venv/bin/python3.12 ]; then
  source .venv/bin/activate
else
  # venvを作成
  rm -rf .venv
  if [ "ubuntu" == "$OsType" ]; then
    python3.12 -m venv .venv --prompt BUWeb
  else
    python3.11 -m venv .venv --prompt BUWeb
  fi
  source .venv/bin/activate
  .venv/bin/python3 -m pip install -U pip setuptools  
fi

# パッケージをインストールする
pip install -r requirements.txt
# playwrightを設定する
if [ "ubuntu" == "$OsType" ]; then
  cmd="sudo bash -c \"source .venv/bin/activate && playwright install-deps\""
  echo $cmd
  eval $cmd
  playwright install chromium
fi

