#!/usr/bin/env python3
import os,sys,shutil
import asyncio
from flask import Flask, abort, render_template, jsonify, send_from_directory, Response, request, make_response, redirect
from concurrent.futures import Future, ThreadPoolExecutor
import subprocess
import uuid
import tempfile
import traceback
from typing import Tuple
import time
import threading
from datetime import datetime
from queue import Queue
from browser_task import BWSession
from datetime import datetime, timedelta
import signal


Pool:ThreadPoolExecutor = ThreadPoolExecutor(20)
TempHome="./tmp/home"

app = Flask(__name__)

novncdir="libs/noVNC-1.5.0"
def is_port_available(port: int) -> bool:
    """指定されたポートが使用可能かチェック"""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('localhost', port))
            return True
    except (socket.error, OSError):
        return False

def find_available_display() -> tuple[int,int,int,int]:
    """利用可能なディスプレイ番号を見つける"""
    display_num:int=None # type: ignore
    vnc_port:int=None # type: ignore
    for num in range(10, 100):
        port = 5900 + num  # VNCサーバー用ポート
        if is_port_available(port):
            display_num=num
            vnc_port = port
            break
    ws_port:int=None # type: ignore
    for num in range(30, 100):
        port = 5000 + num   # websockify用ポート
        if is_port_available(port):
            ws_port = port
            break
    cdn_port:int=None # type: ignore
    for num in range(0, 100):
        port = 9222 + num   # websockify用ポート
        if is_port_available(port):
            cdn_port = port
            break
    if isinstance(display_num,int) and isinstance(vnc_port,int) and isinstance(ws_port,int) and isinstance(cdn_port,int):
        return display_num,vnc_port,ws_port,cdn_port
    raise RuntimeError("利用可能なディスプレイ番号が見つかりません")

def is_proc( proc:subprocess.Popen|None ):
    if proc is not None and proc.poll() is None:
        return True
    return False
    
async def stop_proc( proc:subprocess.Popen|None ):
    if proc is not None:
        try:
            proc.terminate()
        except:
            pass
        try:
            while True:
                try:
                    proc.wait(timeout=0.01)
                    return
                except subprocess.TimeoutExpired:
                    await asyncio.sleep(1)
        except:
            pass

class BwSession:
    def __init__(self,session_id:str,client_addr:str|None):
        self.session_id:str = session_id
        self.client_addr:str|None = client_addr
        self.last_access:datetime = datetime.now()
        self.geometry = "1024x768"
        self.vnc_proc:subprocess.Popen|None = None
        self.websockify_proc:subprocess.Popen|None = None
        self.chrome_process:subprocess.Popen|None = None
        a,b,c,d = find_available_display()
        self.display_num = a
        self.vnc_port = b
        self.ws_port = c
        self.cdn_port = d
        os.makedirs(TempHome,exist_ok=True)
        self.workdir = tempfile.mkdtemp( dir=TempHome,prefix="home",suffix=None)
        # タスク管理用の属性を追加
        self.task_running = False
        self.message_queue: Queue = Queue()
        self.current_task: Future|None = None

    async def setup_vnc_server(self) -> Tuple[str, int]:
        """VNCサーバーをセットアップし、ホスト名とポートを返す"""
        if not is_proc( self.vnc_proc ):
            try:
                # 新しいVNCサーバーを起動（5900番台のポートを使用）
                self.vnc_proc = subprocess.Popen([
                    "Xvnc", f":{self.display_num}",
                    "-geometry", self.geometry,
                    "-depth", "24",
                    "-SecurityTypes", "None",
                    "-localhost", "-alwaysshared", "-ac", "-quiet",
                    "-rfbport", str(self.vnc_port)
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

                # VNCサーバーの起動を待つ
                await asyncio.sleep(1)

                # websockifyを起動（websockifyは5900番台、VNCは6900番台を使用）
                self.websockify_proc = subprocess.Popen([
                    "websockify",
                    "--web", os.path.abspath(novncdir),
                    "--heartbeat", "30",
                    "--verbose",
                    f"0.0.0.0:{self.ws_port}",
                    f"localhost:{self.vnc_port}"
                ])
                # websockifyの起動を待つ
                await asyncio.sleep(1)
            except:
                traceback.print_exc()

        # websockifyのポート番号を返す（クライアントはこのポートに接続）
        hostname = subprocess.getoutput("hostname")
        hostname = "localhost"
        return hostname, self.ws_port

    def launch_chrome(self) -> None:
        """Chromeを起動"""
        if not is_proc( self.chrome_process ):
            env = os.environ.copy()
            env["DISPLAY"] = f":{self.display_num}"
            env["HOME"]=self.workdir
            bcmd=["google-chrome", "--start-maximized", "--no-first-run", "--disable-sync", "--no-default-browser-check", "--disable-gpu", f"--remote-debugging-port={self.cdn_port}" ]
            #bcmd = [ "bwrap", "--bind", "/", "/", "--dev", "/dev", "--tmpfs", home,
            #        "google-chrome", "--start-maximized", "--no-first-run", "--disable-sync", "--no-default-browser-check", f"--remote-debugging-port={self.cdn_port}" ]
            self.chrome_process = subprocess.Popen( bcmd, env=env )

    async def start_task(self, task_info: str) -> None:
        """タスクを開始"""
        if self.task_running:
            raise RuntimeError("タスクが既に実行中です")
        
        self.task_running = True
        #self.current_task = asyncio.create_task( self._run_task(task_info) )
        #self.current_task = threading.Thread(target=self._run_task, args=(task_info,))
        #self.current_task.start()
        self.current_task = Pool.submit(self._start_task,task_info)

    def _start_task(self, task_info: str ) ->None:
        asyncio.run(self._run_task(task_info))

    async def _run_task(self, task_info: str ) ->None:
        def writer(msg):
            self.message_queue.put(msg)
        try:
            session = BWSession(self.cdn_port,writer)
            await session.start(task_info)
            await session.stop()
        except:
            pass
        finally:
            self.task_running = False
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.message_queue.put(f"[{timestamp}] タスクが完了しました")

    async def _run_task_dmy(self, task_info: str) -> None:
        """タスクを実行（非同期）"""
        try:
            #ses = BWSession(self.cdn_port )
            #await ses.start()
            count = 1
            while self.task_running and count <= 10:  # 10回まで実行
                timestamp = datetime.now().strftime("%H:%M:%S")
                message = f"[{timestamp}] タスク実行中... ({count}/10): {task_info}"
                self.message_queue.put(message)
                await asyncio.sleep(5)  # 5秒待機
                count += 1
            
            if self.task_running:  # 正常終了
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.message_queue.put(f"[{timestamp}] タスクが完了しました")
            else:
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.message_queue.put(f"[{timestamp}] タスクがキャンセルされました")
        except:
            traceback.print_exc()
        finally:
            self.task_running = False

    def cancel_task(self) -> None:
        """タスクをキャンセル"""
        if self.task_running:
            self.task_running = False

    async def cleanup(self) -> None:
        """リソースをクリーンアップ"""
        try:
            # タスクをキャンセル
            self.cancel_task()
            
            await stop_proc( self.chrome_process )
            self.chrome_process = None

            await stop_proc( self.websockify_proc )
            self.websockify_proc = None

            await stop_proc( self.vnc_proc )
            self.vnc_proc = None

            # 残存プロセスを強制終了
            if self.display_num>0:
                cmd = f"pkill -f 'Xvnc.*:{self.display_num}'"
                subprocess.run(["/bin/bash", "-c", cmd], check=False)
            if self.vnc_port>0 and self.ws_port>0:
                cmd = f"pkill -f 'websockify.*:{self.ws_port}|:{self.vnc_port}'"
                subprocess.run(["/bin/bash", "-c", cmd], check=False)
                cmd = f"pkill -f 'websockify.*:{self.vnc_port}|:{self.ws_port}'"
                subprocess.run(["/bin/bash", "-c", cmd], check=False)
            try:
                shutil.rmtree(self.workdir)
            except:
                pass
        except Exception as e:
            print(f"VNCサーバー停止中にエラーが発生: {e}")



# セッションデータを保存する辞書
class SessionStore:
    def __init__(self):
        self.sessions: dict[str, BwSession] = {}
        self.cleanup_interval = timedelta(minutes=30)
        self.session_timeout = timedelta(hours=2)
        self._last_cleanup = datetime.now()

    async def cleanup_old_sessions(self):
        """古いセッションをクリーンアップ"""
        now = datetime.now()
        if now - self._last_cleanup < self.cleanup_interval:
            return
        
        expired_sessions = [
            sid for sid, session in self.sessions.items()
            if now - session.last_access > self.session_timeout
        ]
        
        for sid in expired_sessions:
            session = self.sessions[sid]
            await session.cleanup()
            del self.sessions[sid]
        
        self._last_cleanup = now

    def get(self, session_id: str|None) -> BwSession | None:
        """セッションを取得し、タイムスタンプを更新"""
        if session_id and session_id in self.sessions:
            session = self.sessions[session_id]
            session.last_access = datetime.now()
            return session
        return None

    def create(self, session_id: str, client_addr:str|None ) -> BwSession:
        """新しいセッションを作成"""
        session = BwSession(session_id, client_addr)
        self.sessions[session_id] = session
        return session

    async def remove(self, session_id: str) -> None:
        """セッションを削除"""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            await session.cleanup()
            del self.sessions[session_id]

session_store = SessionStore()

def cleanup_sessions():
    print("### CLEANUP SESSIONS ###")
    # 全セッションのクリーンアップ
    if session_store:
        for session_id in list(session_store.sessions.keys()):
            asyncio.run( session_store.remove(session_id) )

@app.route('/')
async def index():
    try:
        client_addr = request.remote_addr
        server_addr = request.host.split(':')[0]
        session_id = request.cookies.get('session_id')
        ses = session_store.get(session_id)
        if ses is None:
            session_id = str(uuid.uuid4())  # 新しい session_id を生成
            session_store.create(session_id,client_addr)
            resp = make_response(redirect(request.url))
            # セキュリティ強化のためのクッキー設定
            resp.set_cookie(
                'session_id',
                session_id,
                httponly=True,  # JavaScriptからのアクセスを防ぐ
                max_age=7200    # 2時間で有効期限切れ
            )
            return resp
        else:
            return send_from_directory('static', 'index.html')
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/favicon.ico')
async def favicon():
    return send_from_directory('static', 'favicon.ico')

@app.route('/style.css')
async def style_css():
    return send_from_directory('static', 'style.css')

@app.route('/novnc/<path:path>')
async def novnc_files(path):
    """noVNCのファイルを提供"""
    return send_from_directory(novncdir, path)

@app.route('/api/<path:api>', methods=['GET','POST'])
async def service_api(api):
    try:
        client_addr = request.remote_addr
        server_addr = request.host.split(':')[0]
        session_id = request.cookies.get('session_id')
        ses:BwSession|None = session_store.get(session_id)
        if ses is None:
            abort(401)

        if api=='start':
            hostname, port = await ses.setup_vnc_server()
            await asyncio.sleep(1)
            ses.launch_chrome()
            return jsonify({
                'status': 'success',
                'host': server_addr,
                'port': ses.ws_port,
            })
        elif api=='execute':
            data = request.get_json()
            task = data.get('task', '')
            if not task:
                return jsonify({'status': 'error','message': 'タスクが指定されていません'}), 400
            if not is_proc(ses.chrome_process):
                return jsonify({'status': 'error', 'message': 'Chromeが起動していません'}), 400
            await ses.start_task(task)
            return jsonify({'status': 'success'})
        elif api=='status':
            return jsonify({
                'vnc_running': is_proc(ses.vnc_proc) and is_proc(ses.websockify_proc),
                'chrome_running': is_proc(ses.chrome_process)
            })
        elif api=='task_progress':
            """SSEエンドポイント - タスクの進捗状況を送信"""
            def generate():
                try:
                    while True:
                        try:
                            # メッセージキューからメッセージを取得
                            message = ses.message_queue.get()
                            yield f"data: {message}\n\n"
                            # タスクが終了した場合は接続を終了
                            if not ses.task_running:
                                break
                        except:
                            break
                finally:
                    pass
            return Response(generate(), mimetype='text/event-stream')
        elif api=='stop':
            await ses.cleanup()
            return jsonify({'status': 'success'})
        elif api=='cancel_task':
            ses.cancel_task()
            return jsonify({'status': 'success'})
        abort(404)
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500
    finally:
        pass

def main():
    def sig_handler(signum, frame) -> None:
        sys.exit(1)
    signal.signal(signal.SIGTERM, sig_handler)
    try:
        app.run(host='0.0.0.0', port=5000)
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        cleanup_sessions()
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)

if __name__ == '__main__':
    main()