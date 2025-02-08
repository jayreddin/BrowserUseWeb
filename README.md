# BrowserUseWeb

Browser-useをFlaskベースのWebアプリケーション化しました。
自然言語でのブラウザ操作を行うサンプル実装です。

https://github.com/browser-use

また、ブラウザ画面の転送にnoVNCを同梱しています。
https://github.com/novnc

## セキュリティ注意事項

サンプル実装なので、通信の暗号化(SSL)は行っていません。
安全なネットワーク内で試用して下さい。

## 主な機能

- Browser-useによるタスク実行
  - 自然言語によるタスク指示をもとにLLMがブラウザを自動操作

- Webインターフェース
  - Browser-useとブラウザをサーバで実行するので、ユーザ(クライアント)での環境構築が不要

- マルチユーザ対応
  - 最大１０ユーザ(セッション)まで同時利用可能

## 前提条件

OS側に、以下のパッケージが必要です：

- Ubuntu 24.04
  - tigervnc-standalone-server
  - websockify
  - google-chrome

- RHEL9(Rocky9,Alma9,...)
  - tigervnc-server
  - python3-websockify
  - google-chrome

## セットアップ

1. リポジトリクローン
```bash
git clone https://github.com/route250/BrowserUseWeb.git
cd BrowserUseWeb
```

2. python仮想環境
```bash
python3.12 -m venv .venv --prompt 'Browser'
source .venv/bin/activate
.venv/bin/python -m pip install -U pip setuptools
```

3. pythonパッケージをインストール
```bash
pip install -r requirements.txt
```

4. 実行権限の付与：
```bash
chmod +x app.py
```

5. 環境変数にAPIキーを設定：
```bash
export OPENAI_API_KEY="your-api-key"
```

6. ファイアウォール設定
- Ubuntu 24.04
```bash
ufw allow 5000/tcp # flaskサーバ用
ufw allow 5030:5099/tcp # websock用
```

- RHEL9(Rocky9,Alma9,...)
```bash
firewall-cmd --add-port=5000/tcp # flaskサーバ用
firewall-cmd --add-port=5030:5099/tcp # websock用
```

7.

ubuntu 24.04の場合、以下の設定が必要

```bash
sudo sysctl -w kernel.apparmor_restrict_unprivileged_unconfined=0
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0
```

## 使用方法

1. アプリケーション起動：
```bash
./app.py
```

2. Webブラウザでアクセス：
```
http://localhost:5000
```

3. 操作手順：
   - タスク入力欄に実行したい内容を日本語で入力
   - 「タスク実行」ボタンをクリックして処理を開始
   - 実行状況は左下のログ出力エリアに表示
   - 「タスクキャンセル」ボタンで処理を停止

## システム構成

- `app.py`: Flaskアプリケーションのメインファイル
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

## 技術仕様

- **バックエンド**
  - Flask: 非同期Webアプリケーションフレームワーク

- **Web自動処理**
  - Browser-use: 自然言語によるブラウザ操作

- **VNC関連**
  - Xvnc: ヘッドレスVNCサーバー
  - websockify: TCPからWebSocketへのプロキシ
  - noVNC: HTML5 VNCクライアント
  - デフォルトの解像度: 1024x1024

- **ブラウザ制御**
  - Chrome DevTools Protocol

## カスタマイズ

browser-useのブラウザ操作がとても遅いので、ボトルネックポイントを探していたら、buldDomTree.jsの実行が遅いことに気づきました。
例えば、アマゾンのトップページにおいて、私の環境で5から6秒程度の処理時間が必要でした。
この部分を高速化できないかと試したら、結局のところbuildDomTreeの処理そのものは1秒以下で完了していて、その結果をpythonへ返信する処理で数秒を要するみたいです。
したがって、buildDomTree.jsの最後を以下のように修正し、
```javascript
return JSON.stringify(buildDomTree(document.body));
```
DomServiceの_build_dom_tree関数の一部を以下のように修正しました。
```python
eval_page = json.loads(await self.page.evaluate(js_code, args))
```
この修正で、_build_dom_tree関数の処理時間は、数分の１から数十分の１になります。

ただし、この修正がすべての環境に有効かどうかわかりません。すくなくとも私の環境では絶大な効果を得ました。

## ライセンス

このプロジェクトはMIT Licenseの下で提供されています。詳細は[LICENSE](LICENSE)ファイルを参照してください。

また、browser-useのライセンス、noVNCのライセンスは別途参照して下さい。
https://github.com/browser-use
https://github.com/novnc

