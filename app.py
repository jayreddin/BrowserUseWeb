#!/usr/bin/env python3
import asyncio
from flask import Flask, render_template, jsonify, send_from_directory, Response, request
from concurrent.futures import Future, ThreadPoolExecutor
import subprocess
import os,shutil
import tempfile
import traceback
from typing import Tuple
import time
import threading
from datetime import datetime
from queue import Queue
from browser_task import BWSession

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
    
def stop_proc( proc:subprocess.Popen|None ):
    if proc is None:
        return
    try:
        proc.terminate()
    except:
        pass
    try:
        proc.wait(timeout=5)
    except:
        pass

class VNCManager:
    def __init__(self):
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

    def setup_vnc_server(self) -> Tuple[str, int]:
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
                time.sleep(1)

                # websockifyを起動（websockifyは5900番台、VNCは6900番台を使用）
                self.websockify_proc = subprocess.Popen([
                    "websockify",
                    "--web", os.path.abspath(novncdir),
                    "--heartbeat", "30",
                    "--verbose",
                    f"0.0.0.0:{self.ws_port}",
                    f"localhost:{self.vnc_port}"
                ])
                time.sleep(2)  # websockifyの起動を待つ
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
            print("### start brwoser-use")
            session = BWSession(self.cdn_port,writer)
            await session.start(task_info)
            print("### stop brwoser-use")
            await session.stop()
        except:
            pass
        finally:
            print("### done brwoser-use")
            self.task_running = False

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
        except:
            traceback.print_exc()
        finally:
            self.task_running = False

    def cancel_task(self) -> None:
        """タスクをキャンセル"""
        if self.task_running:
            self.task_running = False
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.message_queue.put(f"[{timestamp}] タスクがキャンセルされました")

    def cleanup(self) -> None:
        """リソースをクリーンアップ"""
        try:
            # タスクをキャンセル
            self.cancel_task()
            
            stop_proc( self.chrome_process )
            self.chrome_process = None
            try:
                shutil.rmtree(self.workdir)
            except:
                pass

            stop_proc( self.websockify_proc )
            self.websockify_proc = None

            stop_proc( self.vnc_proc )
            self.vnc_proc = None

            # 残存プロセスを強制終了
            cmd = f"pkill -f 'Xvnc.*:{self.display_num}'"
            subprocess.run(["/bin/bash", "-c", cmd], check=False)
            cmd = f"pkill -f 'websockify.*:{self.ws_port}|:{self.vnc_port}'"
            subprocess.run(["/bin/bash", "-c", cmd], check=False)
            cmd = f"pkill -f 'websockify.*:{self.vnc_port}|:{self.ws_port}'"
            subprocess.run(["/bin/bash", "-c", cmd], check=False)
        except Exception as e:
            print(f"VNCサーバー停止中にエラーが発生: {e}")

vnc_manager = VNCManager()

@app.route('/')
async def index():
    return send_from_directory('static', 'index.html')

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

@app.route('/api/start', methods=['POST'])
async def start_chrome():
    try:
        hostaddr = request.host.split(':')[0]
        hostname, port = vnc_manager.setup_vnc_server()
        time.sleep(1)
        vnc_manager.launch_chrome()
        return jsonify({
            'status': 'success',
            'host': hostaddr,
            'port': vnc_manager.ws_port,
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/status')
async def get_status():
    return jsonify({
        'vnc_running': is_proc(vnc_manager.vnc_proc) and is_proc(vnc_manager.websockify_proc),
        'chrome_running': is_proc(vnc_manager.chrome_process)
    })

@app.route('/api/stop', methods=['POST'])
async def stop_chrome():
    try:
        vnc_manager.cleanup()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/execute', methods=['POST'])
async def execute_task():
    """タスクを実行"""
    try:
        if not is_proc(vnc_manager.chrome_process):
            return jsonify({
                'status': 'error',
                'message': 'Chromeが起動していません'
            }), 400

        data = request.get_json()
        task = data.get('task', '')
        if not task:
            return jsonify({
                'status': 'error',
                'message': 'タスクが指定されていません'
            }), 400

        await vnc_manager.start_task(task)
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/cancel_task', methods=['POST'])
async def cancel_task():
    """タスクをキャンセル"""
    try:
        vnc_manager.cancel_task()
        return jsonify({'status': 'success'})
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/task_progress')
async def task_progress():
    """SSEエンドポイント - タスクの進捗状況を送信"""
    def generate():
        while True:
            try:
                # メッセージキューからメッセージを取得
                message = vnc_manager.message_queue.get()
                yield f"data: {message}\n\n"
                
                # タスクが終了した場合は接続を終了
                if not vnc_manager.task_running:
                    break
            except:
                break

    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=5000)
    finally:
        vnc_manager.cleanup()
