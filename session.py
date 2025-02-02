import sys, os, shutil, subprocess, traceback, tempfile
from datetime import datetime, timedelta
from queue import Queue
from concurrent.futures import ThreadPoolExecutor, Future
import asyncio
import uuid
from browser_task import BwTask

def is_port_available(port: int) -> bool:
    """指定されたポートが使用可能かチェック"""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('localhost', port))
            return True
    except (socket.error, OSError):
        return False

def find_available_display() -> tuple[int,int]:
    """利用可能なディスプレイ番号を見つける"""
    for num in range(10, 100):
        port = 5900 + num  # VNCサーバー用ポート
        if is_port_available(port):
            return num, port
    raise RuntimeError("利用可能なディスプレイ番号が見つかりません")

def find_ws_port() -> int:
    for num in range(30, 100):
        port = 5000 + num   # websockify用ポート
        if is_port_available(port):
            return port
    raise RuntimeError("利用可能なwebsockポートが見つかりません")

def find_cdn_port() -> int:
    """利用可能なディスプレイ番号を見つける"""
    for num in range(0, 100):
        port = 9222 + num   # websockify用ポート
        if is_port_available(port):
            return port
    raise RuntimeError("利用可能なCDNポートが見つかりません")

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
    def __init__(self,session_id:str,client_addr:str|None, *, workdir:str, novncdir:str, Pool:ThreadPoolExecutor):
        self.session_id:str = session_id
        self.client_addr:str|None = client_addr
        self.last_access:datetime = datetime.now()
        self.TempHome:str = workdir
        self.novncdir:str = novncdir
        self.Pool:ThreadPoolExecutor = Pool
        self.geometry = "1024x1024"
        self.vnc_proc:subprocess.Popen|None = None
        self.websockify_proc:subprocess.Popen|None = None
        self.chrome_process:subprocess.Popen|None = None
        self.display_num:int = 0
        self.vnc_port:int = 0
        self.ws_port:int = 0
        self.cdn_port:int = 0
        self.workdir = workdir
        # タスク管理用の属性を追加
        self.task_running = False
        self.message_queue: Queue = Queue()
        self.current_task: Future|None = None

    def is_vnc_running(self) -> int:
        return self.display_num if self.display_num>0 and is_proc(self.vnc_proc) else 0

    def is_websockify_running(self) -> int:
        return self.ws_port if self.ws_port>0 and is_proc(self.websockify_proc) else 0

    def is_chrome_running(self) -> int:
        return self.cdn_port if self.cdn_port>0 and is_proc(self.chrome_process) else 0

    def is_ready(self) -> bool:
        return self.is_vnc_running()>0 and self.is_websockify_running()>0 and self.is_chrome_running()>0

    async def setup_vnc_server(self) -> None:
        """VNCサーバーをセットアップし、ホスト名とポートを返す"""
        if not is_proc( self.vnc_proc ):
            try:
                display_num,vnc_port = find_available_display()
                # 新しいVNCサーバーを起動（5900番台のポートを使用）
                self.vnc_proc = subprocess.Popen([
                    "Xvnc", f":{display_num}",
                    "-geometry", self.geometry,
                    "-depth", "24",
                    "-SecurityTypes", "None",
                    "-localhost", "-alwaysshared", "-ac", "-quiet",
                    "-rfbport", str(vnc_port)
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                # VNCサーバーの起動を待つ
                await asyncio.sleep(1)
                self.display_num = display_num
                self.vnc_port = vnc_port


                # websockifyを起動（websockifyは5900番台、VNCは6900番台を使用）
                ws_port = find_ws_port()
                self.websockify_proc = subprocess.Popen([
                    "websockify",
                    "--web", os.path.abspath(self.novncdir),
                    "--heartbeat", "30",
                    f"0.0.0.0:{ws_port}",
                    f"localhost:{self.vnc_port}"
                ])
                # websockifyの起動を待つ
                await asyncio.sleep(1)
                self.ws_port = ws_port
            except:
                traceback.print_exc()

    async def launch_chrome(self) -> None:
        """Chromeを起動"""
        if not is_proc( self.chrome_process ):
            cdn_port = find_cdn_port()
            env = os.environ.copy()
            env["DISPLAY"] = f":{self.display_num}"
            env["HOME"]=self.workdir
            bcmd=["google-chrome", "--start-maximized", "--no-first-run", "--disable-sync", "--no-default-browser-check", "--disable-gpu", f"--remote-debugging-port={cdn_port}" ]
            #bcmd = [ "bwrap", "--bind", "/", "/", "--dev", "/dev", "--tmpfs", home,
            #        "google-chrome", "--start-maximized", "--no-first-run", "--disable-sync", "--no-default-browser-check", f"--remote-debugging-port={self.cdn_port}" ]
            self.chrome_process = subprocess.Popen( bcmd, env=env )
            self.cdn_port = cdn_port

    async def setup_browser(self) ->None:
        await self.setup_vnc_server()
        await self.launch_chrome()

    async def start_task(self, task_info: str) -> None:
        """タスクを開始"""
        if self.task_running:
            raise RuntimeError("タスクが既に実行中です")
        
        self.task_running = True
        self.current_task = self.Pool.submit(self._start_task,task_info)

    def _start_task(self, task_info: str ) ->None:
        asyncio.run(self._run_task(task_info))

    async def _run_task(self, prompt: str ) ->None:
        def writer(msg):
            self.message_queue.put(msg)
        try:
            await self.setup_browser()
            task = BwTask(self.cdn_port,writer)
            await task.start(prompt)
            await task.stop()
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
    def __init__(self, *, TempHome:str="tmp/home", novncdir:str="libs/noVNC-1.5.0", Pool:ThreadPoolExecutor|None=None):
        self.sessions: dict[str, BwSession] = {}
        self.TempHome:str = TempHome
        self.novncdir:str = novncdir
        self.Pool:ThreadPoolExecutor = Pool if isinstance(Pool,ThreadPoolExecutor) else ThreadPoolExecutor()
        self.cleanup_interval:timedelta = timedelta(minutes=30)
        self.session_timeout:timedelta = timedelta(hours=2)
        self._last_cleanup:datetime = datetime.now()

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

    def create(self, session_id: str|None, client_addr:str|None ) -> BwSession:
        """新しいセッションを作成"""
        if session_id is None:
            session_id = str(uuid.uuid4())
        os.makedirs(self.TempHome,exist_ok=True)
        workdir = tempfile.mkdtemp( dir=self.TempHome,prefix="work_",suffix=None)
        session = BwSession(session_id, client_addr=client_addr, workdir=workdir, novncdir=self.novncdir, Pool=self.Pool)
        self.sessions[session_id] = session
        return session

    async def remove(self, session_id: str) -> None:
        """セッションを削除"""
        if session_id in self.sessions:
            session = self.sessions[session_id]
            await session.cleanup()
            del self.sessions[session_id]
