<div align="right">日本語/<a href="README_en.md">English</a></div>

# BrowserUseWeb

Browser-useをQuartベースのWebアプリケーション化しました。
自然言語でのブラウザ操作を行うサンプル実装です。

[Browser-use:https://github.com/browser-use](https://github.com/browser-use)

また、ブラウザ画面の転送にnoVNCを同梱しています。

[noVNC:https://github.com/novnc](https://github.com/novnc)

## セキュリティ注意事項

サンプル実装なので、通信の暗号化(SSL)は行っていません。
安全なネットワーク内で試用して下さい。

## 主な機能

- Browser-useによるタスク実行
  自然言語によるタスク指示をもとにLLMがブラウザを自動操作

- Webインターフェース
  Browser-useとブラウザをサーバで実行するので、ユーザ(クライアント)での環境構築が不要

- マルチユーザ対応
  最大１０ユーザ(セッション)まで同時利用可能

## 前提条件

OS側に、以下のパッケージが必要です：

- Ubuntu 24.04
  tigervnc-standalone-server
  bubblewrap

- RHEL9(Rocky9,Alma9,...)
  python3.11
  tigervnc-server
  bubblewrap

## セットアップ

1. リポジトリクローン

  ```bash
  $ git clone https://github.com/route250/BrowserUseWeb.git
  $ cd BrowserUseWeb
  ```

2. python仮想環境

  ```bash
  $ python3.12 -m venv .venv --prompt 'Browser'
  $ source .venv/bin/activate
  (.venv) $ .venv/bin/python -m pip install -U pip setuptools
```

3. pythonパッケージをインストール

  ```bash
  (.venv) $ pip install -r requirements.txt
  ```

4. ブラウザのセットアップ

  4.1 playwrightでブラウザを使用する場合

  - playwrightでブラウザに必要なパッケージをインストールして下さい。

    ```bash
    (.venv) $ sudo /bin/bash             # パッケージインストールのためにrootにする
    # source .venv/bin/activate          # rootでも仮想環境をアクティベートして
    (.venv) # playwright install-deps    # playwrightで、パッケージをインストールする
    (.venv) # exit
    ```

  　- playwrightでchromiumをインストールして下さい。

    ```bash
    (.venv) $ playwright install chromium
    ```
  4.2 google-chromeを使用する場合

    いつものようにgoogle-chromeをインストールしてください。
    もちろん、すでにインストールされていれば、そのままでOKです。

  4.3 その他

    使用するブラウザによって、buweb/scripts/start_browser.shを編集して、変数CHROME_BINが適切に設定されるようにして下さい。

5. 実行権限の付与：

  ```bash
  chmod +x app.py
  chmod +x service_start.sh
  ```

6. config.env にAPIキーを設定：

  ```bash:config.env
  OPENAI_API_KEY="your-api-key"
  GOOGLE_API_KEY="your-api-key"
  ```

7. ファイアウォール設定

  - Ubuntu 24.04

    ```bash
    ufw allow 5000/tcp # quartサーバ用
    ufw allow 5030:5099/tcp # websock用
    ```

  - RHEL9(Rocky9,Alma9,...)

    ```bash
    firewall-cmd --add-port=5000/tcp # quartサーバ用
    firewall-cmd --add-port=5030:5099/tcp # websock用
    ```

8. セキュリティ関連

  - ubuntu 24.04の場合、以下の設定が必要

    ```bash
    sudo sysctl -w kernel.apparmor_restrict_unprivileged_unconfined=0
    sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
    ```

  - SELinuxの警告

    SELinuxで警告が出て、「selinuxuser_execmod booleanがなんやかんや」と言われるが、いまのところ無視して実行している。

## 起動方法

1. シェルスクリプトで起動する場合:

  ```bash
  ./service_start.sh
  ```

2. VS Codeで実行する場合

  app.pyを実行

## 使い方

1. Webブラウザでアクセス：

  ```text
  http://localhost:5000
  ```

2. 操作手順：

   - タスク入力欄に実行したい内容を日本語で入力
   - 「タスク実行」ボタンをクリックして処理を開始
   - 実行状況は左下のログ出力エリアに表示
   - 「タスクキャンセル」ボタンで処理を停止

## ブラウザが起動しない時

以下のシェルスクリプトを修正すると動くかもしれません。

- buweb/scripts/start_browser.sh
- buweb/scripts/start_vnc.sh

## システム構成

- `service_start.sh`: 起動シェルスクリプト
- `app.py`: Quartアプリケーションのメインファイル
  - HTTPリクエストのハンドリング
  - セッション管理
  - APIエンドポイントの提供
- `session.py`: セッション管理クラス
  - Xvncサーバーの自動起動/停止
  - websockifyによるWebSocket接続
  - Chromeブラウザの起動管理
  - セッションのクリーンアップ
- `browser_task.py`: ブラウザ自動操作
  - 自然言語によるタスク指示
  - ブラウザ操作の実行制御
  - タスク進捗の管理
- `static/index.html`: フロントエンドインターフェース
  - リアルタイムステータス表示
  - WebSocket/SSE通信
  - noVNCによるブラウザベースのVNCクライアント
- `buweb/scripts/start_vnc.sh`: VNCサーバ起動スクリプト
  - Xvncの環境設定と起動停止
- `buweb/scripts/start_browser.sh`: ブラウザ起動スクリプト
  - bwrapによる環境分離
  - ブラウザの起動と停止
  
## 技術仕様

- **バックエンド**
  - Quart: 非同期Webアプリケーションフレームワーク

- **Web自動処理**
  - Browser-use: 自然言語によるブラウザ操作

- **VNC関連**
  - Xvnc: ヘッドレスVNCサーバー
  - websockify: TCPからWebSocketへのプロキシ
  - noVNC: HTML5 VNCクライアント
  - デフォルトの解像度: 1024x1024

- **ブラウザ制御**
  - Chrome DevTools Protocol

## ライセンス

このプロジェクトはMIT Licenseの下で提供されています。詳細は[LICENSE](LICENSE)ファイルを参照してください。

また、browser-useのライセンス、noVNCのライセンスは別途参照して下さい。
[Browser-use:https://github.com/browser-use](https://github.com/browser-use)
[noVNC:https://github.com/novnc](https://github.com/novnc)
