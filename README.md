# VNC Chrome Controller

FlaskベースのWebアプリケーションで、VNCサーバーを介してChromeブラウザをリモート制御します。

## 機能

- Webインターフェースによる操作（左右分割レイアウト）
- VNCサーバーの自動起動/停止
- Chromeブラウザの制御
- noVNCによるブラウザベースのVNCクライアント

## 前提条件

以下のパッケージが必要です：

```bash
# VNCサーバーとnoVNCのインストール
sudo dnf install -y tigervnc-server novnc python3-websockify

# Chromeのインストール（ChromiumまたはGoogle Chrome）
sudo dnf install -y chromium

# Pythonパッケージのインストール
python -m pip install -r requirements.txt
```

## セットアップ

1. スクリプトを実行可能にします：
```bash
chmod +x app.py
```

## 使用方法

1. アプリケーションの起動：
```bash
./app.py
```

2. Webブラウザで以下のURLにアクセス：
```
http://localhost:5000
```

3. 操作方法：
   - 左側の操作パネルで「Chrome起動」ボタンをクリック
   - 右側のペインにChromeの画面が表示されます
   - 「停止」ボタンでChromeとVNCサーバーを終了

## アーキテクチャ

- `app.py`: Flaskアプリケーションのメインファイル
- `templates/index.html`: Webインターフェースのテンプレート
- `static/style.css`: CSSスタイルシート
- `requirements.txt`: 必要なPythonパッケージの一覧

## 技術的な詳細

- VNCサーバー: Xvnc（TigerVNC）を使用
- Webソケットプロキシ: websockify
- VNCクライアント: noVNC（ブラウザベース）
- ディスプレイ番号: :7（ポート5907）
- 解像度: 1024x768

## 注意事項

- セキュリティのため、信頼できるネットワーク内でのみ使用してください
- 必要に応じてファイアウォールでポートを開放してください：
  - Flask: 5000/tcp
  - VNC: 5907/tcp
  - websockify: 5907/tcp (VNCプロキシ)

## トラブルシューティング

1. VNCサーバーが起動しない場合：
```bash
# 既存のVNCプロセスを確認
ps aux | grep Xvnc

# 必要に応じて既存のプロセスを停止
kill -9 <プロセスID>
```

2. Chromeが起動しない場合：
- `app.py`内の`google-chrome`コマンドを`chromium-browser`に変更してください

3. noVNC接続エラーの場合：
- websockifyが正しく起動しているか確認
- ファイアウォールの設定を確認
- `/usr/share/novnc`にnoVNCファイルが存在することを確認
