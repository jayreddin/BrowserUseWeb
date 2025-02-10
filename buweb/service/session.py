import sys, os, shutil, subprocess, traceback, tempfile
from datetime import datetime, timedelta
import time
from queue import Queue
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, Future
import asyncio
import aiohttp
import random,string
from langchain_core.caches import BaseCache
from langchain_core.caches import InMemoryCache
from langchain_community.cache import SQLiteCache
from buweb.model.model import LLM
from buweb.task.operator import BwTask
from logging import Logger,getLogger
logger:Logger = getLogger(__name__)

class CanNotStartException(Exception):
    pass

HOSTSFILE:str = 'hosts.adblock'

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
    raise CanNotStartException("利用可能なディスプレイ番号が見つかりません")

def find_ws_port() -> int:
    for num in range(30, 100):
        port = 5000 + num   # websockify用ポート
        if is_port_available(port):
            return port
    raise CanNotStartException("利用可能なwebsockポートが見つかりません")

def find_cdn_port() -> int:
    """利用可能なディスプレイ番号を見つける"""
    for num in range(0, 100):
        port = 9222 + num   # websockify用ポート
        if is_port_available(port):
            return port
    raise CanNotStartException("利用可能なCDNポートが見つかりません")

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

async def download_hosts_file_async(save_path: str):
    url = "https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts"
    timeout = aiohttp.ClientTimeout(total=10)  # 正しい ClientTimeout の設定

    try:
        content:bytes|None = None
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    print(f"`hosts` ファイルのダウンロードに失敗しました: HTTP {response.status}")
                    return
                # ファイルを非同期で保存
                content = await response.read()
        if content is not None:
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(content)
                if os.path.exists(save_path):
                    os.replace(temp_file.name, save_path)  # 上書き
                    print(f"`hosts` ファイルを上書きしました: {save_path}")
                else:
                    shutil.move(temp_file.name, save_path)  # 新規移動
                    print(f"`hosts` ファイルを移動しました: {save_path}")

    except Exception as e:
        print(f"`hosts` ファイルのダウンロード中にエラーが発生しました: {e}")

class BwSession:
    def __init__(self,session_id:str, server_addr:str, client_addr:str|None, *, dir:str, hostsfile:str, Pool:ThreadPoolExecutor):
        self.session_id:str = session_id
        self.server_addr:str = server_addr
        self.client_addr:str|None = client_addr
        self.last_access:datetime = datetime.now()
        self.WorkDir:str = dir
        self.hostsfile:str = hostsfile
        self.Pool:ThreadPoolExecutor = Pool
        self.geometry = "1024x900"
        self.vnc_proc:subprocess.Popen|None = None
        self.websockify_proc:subprocess.Popen|None = None
        self.chrome_process:subprocess.Popen|None = None
        self.display_num:int = 0
        self.vnc_port:int = 0
        self.ws_port:int = 0
        self.cdp_port:int = 0
        # 設定
        self._operator_llm:LLM = LLM.Gemini20Flash
        self._planner_llm:LLM|None = None
        # タスク管理用の属性を追加
        self._task_expand:bool = False
        self.task_running:bool = False
        self.task:BwTask|None = None
        self.message_queue: Queue = Queue()
        self.current_task: Future|None = None

    def touch(self):
        self.last_access:datetime = datetime.now()

    def _write_msg(self,msg):
        self.touch()
        self.message_queue.put(msg)

    def is_vnc_running(self) -> int:
        return self.display_num if self.display_num>0 and is_proc(self.vnc_proc) else 0

    def is_websockify_running(self) -> int:
        return self.ws_port if self.ws_port>0 and is_proc(self.websockify_proc) else 0

    def is_chrome_running(self) -> int:
        return self.cdp_port if self.cdp_port>0 and is_proc(self.chrome_process) else 0

    def is_ready(self) -> bool:
        return self.is_vnc_running()>0 and self.is_websockify_running()>0 and self.is_chrome_running()>0

    def is_task(self) ->int:
        if self.task_running:
            return 1
        else:
            return 0

    def get_status(self) ->dict:
        res = {
            'status': 'success',
            'sid': self.session_id,
            'sv': self.server_addr,
            'vnc': self.is_vnc_running(),
            'ws': self.is_websockify_running(),
            'br': self.is_chrome_running(),
            'task': self.is_task(),
        }
        return res

    async def wait_port(self,proc:subprocess.Popen, port:int, timeout_sec:float):
        exit_sec:float = time.time() + timeout_sec
        while not is_port_available(port) and is_proc(proc):
            self.touch()
            if time.time()>exit_sec:
                raise CanNotStartException(f"ポート番号{port}が有効になりませんでした")
            await asyncio.sleep(.2)

    async def setup_vnc_server(self) -> None:
        """VNCサーバーをセットアップし、ホスト名とポートを返す"""
        if is_proc( self.vnc_proc ) and is_proc(self.websockify_proc):
            return

        self.vnc_proc = None
        self.display_num = 0
        self.vnc_port = 0
        self.websockify_proc = None
        self.ws_port = 0

        await stop_proc(self.vnc_proc)
        await stop_proc(self.websockify_proc)

        vnc_proc:subprocess.Popen|None = None
        ws_proc:subprocess.Popen|None = None
        try:
            display_num,vnc_port = find_available_display()
            # 新しいVNCサーバーを起動（5900番台のポートを使用）
            vnc_proc = subprocess.Popen([
                "Xvnc", f":{display_num}",
                "-geometry", self.geometry,
                "-depth", "24",
                "-SecurityTypes", "None",
                "-localhost", "-alwaysshared", "-ac", "-quiet",
                "-rfbport", str(vnc_port)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # VNCサーバーの起動を待つ
            await self.wait_port( vnc_proc, vnc_port, 10.0)
            if vnc_proc.poll() is not None:
                raise CanNotStartException("Xvncが起動できませんでした")

            # websockifyを起動（websockifyは5900番台、VNCは6900番台を使用）
            ws_port = find_ws_port()
            ws_proc = subprocess.Popen([
                "websockify",
                "--heartbeat", "30",
                f"0.0.0.0:{ws_port}",
                f"localhost:{vnc_port}"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            # websockifyの起動を待つ
            await self.wait_port(ws_proc,ws_port,10.0)
            if ws_proc.poll() is not None:
                raise CanNotStartException("websockifyが起動できませんでした")
            
            logger.info(f"[{self.session_id}] Started Xvnc pid:{vnc_proc.pid} :{display_num} port:{vnc_port} WebSock pid:{ws_proc.pid} port:{ws_port}")
            self.vnc_proc = vnc_proc
            self.display_num = display_num
            self.vnc_port = vnc_port
            self.websockify_proc = ws_proc
            self.ws_port = ws_port

        except Exception as ex:
            await stop_proc(vnc_proc)
            await stop_proc(ws_proc)
            raise ex

    async def launch_chrome(self) -> None:
        """Chromeを起動"""
        if is_proc( self.chrome_process ):
            return
        self.chrome_process = None
        self.cdp_port = 0
        chrome_process:subprocess.Popen|None = None
        try:
            cdp_port = find_cdn_port()
            prof = f"{self.WorkDir}/.config/google-chrome/Default"
            os.makedirs(prof,exist_ok=True)
            chrome_cmd=["/opt/google/chrome/google-chrome",
                # "--kiosk",
                "--no-first-run", "--disable-sync", "--no-default-browser-check","--password-store=basic",
                "--disable-extensions",
                "--disable-metrics", "--disable-metrics-reporting", "--disable-crash-reporter", "--disable-logging",
                "--disable-gpu", "--disable-webgl", "--disable-vulkan", "--disable-accelerated-layers", "--enable-unsafe-swiftshader",
                "--disable-smooth-scrolling", "--disable-spell-checking", "--disable-remote-fonts", "--disable-dev-shm-usage",
                f"--remote-debugging-port={cdp_port}"
            ]
            # "--disable-popup-blocking",
            orig_home = os.environ['HOME']
            env = os.environ.copy()
            env["DISPLAY"] = f":{self.display_num}"
            sw = 1
            if sw==0:
                env["HOME"]=self.WorkDir
                chrome_process = subprocess.Popen( chrome_cmd, cwd=self.WorkDir, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL )
            else:
                bcmd = [ "bwrap", "--bind", "/", "/", "--dev", "/dev", "--bind", self.WorkDir, orig_home, "--chdir", orig_home ]
                if os.path.exists(self.hostsfile):
                    bcmd.extend( ["--bind",self.hostsfile,"/etc/hosts"])
                bcmd.extend(chrome_cmd)
                chrome_process = subprocess.Popen( bcmd, cwd=self.WorkDir, env=env )
            await self.wait_port(chrome_process,cdp_port,30.0)
            if chrome_process.poll() is not None:
                raise CanNotStartException("google-chromeが起動できませんでした")
            self.chrome_process = chrome_process
            self.cdp_port = cdp_port
        except Exception as ex:
            await stop_proc(chrome_process)
            raise ex

    async def start_browser(self) ->dict:
        try:
            self.touch()
            await self.setup_vnc_server()
            if is_proc(self.vnc_proc) and is_proc(self.websockify_proc):
                await self.launch_chrome()
        except CanNotStartException as ex:
            logger.warning(f"[{self.session_id}] {str(ex)}")
        except Exception as ex:
            logger.exception(f"[{self.session_id}] {str(ex)}")
        return self.get_status()

    async def start_task(self, task_info: str, llm:LLM, planner_llm:LLM|None, llm_cache:BaseCache|None, sensitive_data:dict[str,str]|None) -> None:
        """タスクを開始"""
        self.touch()
        if self.task is not None or self.task_running:
            raise RuntimeError("タスクが既に実行中です")
        else:
            self.task_running = True
            self.current_task = self.Pool.submit(self._start_task,task_info, llm, planner_llm, llm_cache, sensitive_data )

    def _start_task(self, prompt: str, llm:LLM, planner_llm:LLM|None,  llm_cache:BaseCache|None, sensitive_data:dict[str,str]|None ) ->None:
        asyncio.run(self._run_task(prompt,llm, planner_llm, llm_cache, sensitive_data))

    async def _run_task(self, prompt: str, llm:LLM, planner_llm:LLM|None,  llm_cache:BaseCache|None, sensitive_data:dict[str,str]|None) ->None:
        try:
            self.touch()
            await self.setup_vnc_server()
            await self.launch_chrome()
            self.task = BwTask( dir=self.WorkDir,
                            llm_cache=llm_cache, llm=llm, plan_llm=planner_llm,
                            cdp_port=self.cdp_port,
                            sensitive_data=sensitive_data,
                            writer=self._write_msg)
            await self.task.start(prompt)
            await self.task.stop()
        except CanNotStartException as ex:
            logger.warning(f"[{self.session_id}] {str(ex)}")
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.message_queue.put(f"[{timestamp}] {str(ex)}")
        except Exception as ex:
            logger.exception(f"[{self.session_id}] {str(ex)}")
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.message_queue.put(f"[{timestamp}] {str(ex)}")
        finally:
            self.task_running = False
            self.task = None
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.message_queue.put(f"[{timestamp}] タスクが完了しました")

    async def cancel_task(self) -> dict:
        """タスクをキャンセル"""
        if self.task_running:
            while self.task_running:
                if self.task is not None:
                    await self.task.stop()
                await asyncio.sleep(0.5)
        return self.get_status()

    async def stop_browser(self) ->dict:
        try:
            logger.info(f"[{self.session_id}] stop_browser")
            # タスクをキャンセル
            await self.cancel_task()
            
            await stop_proc( self.chrome_process )
            self.chrome_process = None
            self.cdp_port = 0

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
            self.display_num = 0
            self.vnc_port = 0
            self.ws_port = 0
        except Exception as e:
            logger.exception(f"[{self.session_id}] VNCサーバー停止中にエラーが発生: {str(e)}")
        return self.get_status()

    async def store_file(self, file_path:str, data:bytes) -> None:
        """ファイルを保存"""
        store_path = os.path.join(self.WorkDir, file_path)
        with open(store_path, "wb") as f:
            f.write(data)

    async def cleanup(self) -> None:
        """リソースをクリーンアップ"""
        await self.stop_browser()
        try:
            shutil.rmtree(self.WorkDir)
        except Exception as e:
            logger.exception(f"[{self.session_id}] VNCサーバー停止中にエラーが発生: {str(e)}")

# セッションデータを保存する辞書
class SessionStore:
    def __init__(self, *, max_sessions:int=3, dir:str="tmp/sessions", Pool:ThreadPoolExecutor|None=None):
        self._lock = Lock()
        self._connect:int = 0
        self._max_sessions:int = max_sessions
        self.sessions: dict[str, BwSession] = {}
        self.SessionsDir:str = os.path.abspath(dir)
        self.hostsfile:str = os.path.join(self.SessionsDir,'hosts.adblock')
        self.Pool:ThreadPoolExecutor = Pool if isinstance(Pool,ThreadPoolExecutor) else ThreadPoolExecutor()
        self.cleanup_interval:timedelta = timedelta(minutes=30)
        self.session_timeout:timedelta = timedelta(hours=2)
        self._last_cleanup:datetime = datetime.now()
        self._sweeper_futute:Future|None = None
        self._llm_cache_path:str = os.path.join(self.SessionsDir,'langchain_cache.db')
        self._llm_cache:BaseCache = SQLiteCache(self._llm_cache_path)
        # 設定
        self._operator_llm:LLM = LLM.Gemini20Flash
        self._planner_llm:LLM|None = None

    async def _start_sweeper(self):
        if self._sweeper_futute is None:
            self._sweeper_futute = self.Pool.submit( self._sweeper_task )

    def _sweeper_task(self):
        try:
            logger.info("start swepper")
            while True:
                # 広告ブロック用のhostsファイルを更新する
                now = time.time()
                last_mod_sec:float = os.path.getmtime(self.hostsfile) if os.path.exists(self.hostsfile) else 0.0
                if (now-last_mod_sec)>3600.0:
                    asyncio.run( download_hosts_file_async(self.hostsfile) )
                # セッションをクリーンアップする
                asyncio.run( self.cleanup_old_sessions() )
                if len(self.sessions)==0:
                    self._sweeper_futute = None
                    return
                time.sleep(2.0)
        except:
            logger.exception("error in sweeper")
        finally:
            logger.info("end swepper")
            self._sweeper_futute = None

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

    def setup_session( self, session:BwSession ):
        session._operator_llm = self._operator_llm
        session._planner_llm = self._planner_llm

    def setup_sessions( self ):
        for session_id,session in self.sessions.items():
            self.setup_session(session)

    def configure(self, operator_llm:LLM, planner_llm:LLM|None, max_sessions:int ):
        if max_sessions<0 or 20<max_sessions:
            raise ValueError(f"invalid number {max_sessions}")
        self._operator_llm = operator_llm
        self._planner_llm = planner_llm
        self._max_sessions = max_sessions
        self.setup_sessions()

    def incr(self):
        with self._lock:
            self._connect+=1
    def decr(self):
        with self._lock:
            self._connect-=1

    def get_status(self) ->tuple[int,int,int]:
        with self._lock:
            return self._connect, len(self.sessions), self._max_sessions

    async def get(self, session_id: str|None) -> BwSession | None:
        """セッションを取得し、タイムスタンプを更新"""
        if session_id and session_id in self.sessions:
            session = self.sessions[session_id]
            session.touch()
            return session
        return None

    async def create(self, server_addr:str, client_addr:str|None ) -> BwSession|None:
        """新しいセッションを作成"""
        if len(self.sessions)>=self._max_sessions:
            return None
        while True:
            session_id = session_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
            if session_id not in self.sessions:
                break
        workdir = os.path.join( self.SessionsDir, f"session_{session_id}")
        logger.info(f"[{session_id}] create session")
        os.makedirs(workdir,exist_ok=False)
        session = BwSession(session_id, server_addr=server_addr, client_addr=client_addr, dir=workdir, hostsfile=self.hostsfile, Pool=self.Pool)
        self.setup_session(session)
        self.sessions[session_id] = session
        await self._start_sweeper()
        return session

    async def remove(self, session_id: str) -> None:
        """セッションを削除"""
        if session_id in self.sessions:
            logger.info(f"[{session_id}] remove session")
            session = self.sessions[session_id]
            await session.cleanup()
            del self.sessions[session_id]

    async def cleanup_all(self):
        for session_id in list(self.sessions.keys()):
            await self.remove(session_id)

