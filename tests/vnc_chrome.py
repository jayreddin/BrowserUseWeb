#!/usr/bin/env python3

import os
import subprocess
import time
from typing import NoReturn, Tuple

def find_available_display() -> int:
    """利用可能なディスプレイ番号を見つける"""
    for display_num in range(1, 100):
        port = 5900 + display_num
        try:
            # ポートが使用中かチェック
            result = subprocess.run(
                ["lsof", "-i", f":{port}"],
                capture_output=True,
                check=False
            )
            if result.returncode != 0:
                return display_num
        except subprocess.SubprocessError:
            return display_num
    raise RuntimeError("利用可能なディスプレイ番号が見つかりません")

def setup_vnc_server() -> Tuple[str, int]:
    """VNCサーバーをセットアップし、ディスプレイ番号を返す"""
    # 利用可能なディスプレイ番号を見つける
    display_num = find_available_display()
    
    # 新しいVNCサーバーを起動
    geometry = "1024x768"
    try:
        subprocess.run([
            "vncserver", f":{display_num}",
            "-geometry", geometry,
            "-depth", "24",
            "-SecurityTypes", "None",
            "-localhost",
            "-alwaysshared"
        ], check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"VNCサーバーの起動に失敗しました: {e.stderr.decode()}")
    
    # ホスト名とポート番号を取得
    hostname = subprocess.getoutput("hostname")
    port = 5900 + display_num
    
    return hostname, port

def launch_chrome(display_num: int) -> None:
    """指定されたディスプレイでChromeを起動"""
    os.environ["DISPLAY"] = f":{display_num}"
    
    # Chromeを起動（バックグラウンドで）
    subprocess.Popen([
        "google-chrome",
        "--no-sandbox",
        "--start-maximized",
        "https://www.google.com"  # デフォルトページ
    ])

def main() -> None:
    display_num = None
    try:
        # VNCサーバーをセットアップ
        hostname, port = setup_vnc_server()
        display_num = port - 5900  # ポート番号からディスプレイ番号を計算
        print(f"VNCサーバーが起動しました")
        print(f"ホスト: {hostname}")
        print(f"ポート: {port}")
        print(f"接続文字列: {hostname}:{port}")
        
        # Chromeを起動
        launch_chrome(display_num)
        print("Chromeを起動しました")
        
        # プロセスを維持
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nシャットダウンします...")
    except Exception as e:
        print(f"エラーが発生しました: {e}")
    finally:
        if display_num is not None:
            try:
                # VNCサーバーをクリーンアップ
                subprocess.run(["vncserver", "-kill", f":{display_num}"], check=True)
                print("VNCサーバーを停止しました")
            except subprocess.SubprocessError as e:
                print(f"VNCサーバーの停止中にエラーが発生しました: {e}")

if __name__ == "__main__":
    main()
