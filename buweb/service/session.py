import sys, os, shutil, subprocess, traceback, tempfile
from datetime import datetime, timedelta
import time
import json
from queue import Queue, Empty
from threading import Lock
from concurrent.futures import ThreadPoolExecutor, Future
import asyncio
from asyncio import Task
import aiohttp
import random,string
from importlib.resources import files
from langchain_core.caches import BaseCache
from langchain_core.caches import InMemoryCache
from langchain_community.cache import SQLiteCache
from buweb.model.model import LLM
from buweb.model.translate import Translate
from buweb.agent.buw_agent import BuwWriter
from buweb.task.operator import BwTask
from buweb.task.research import BwResearchTask
from logging import Logger,getLogger
logger:Logger = getLogger(__name__)

class CanNotStartException(Exception):
    pass

HOSTSFILE:str = 'hosts.adblock'

def is_port_available(port: int) -> bool:
    # Check if the specified port is available
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('localhost', port))
            return True
    except (socket.error, OSError):
        return False

def find_available_display() -> tuple[int,int]:
    """Find available display numbers"""
    for num in range(10, 100):
        port = 5900 + num # Port for VNC server
        if is_port_available(port):
            return num, port
    raise CanNotStartException("No available display number found")

def find_ws_port() -> int:
    for num in range(30, 100):
        port = 5000 + num # port for websockify
        if is_port_available(port):
            return port
    raise CanNotStartException("No available websock port found")

def find_cdn_port() -> int:
    """Find available display numbers"""
    for num in range(0, 100):
        port = 9222 + num # port for websockify
        if is_port_available(port):
            return port
    raise CanNotStartException("No available CDN port found")

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
    timeout = aiohttp.ClientTimeout(total=10) # Correct ClientTimeout setting

    try:
        content:bytes|None = None
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=timeout) as response:
                if response.status != 200:
                    print(f"Failed to download `hosts` file: HTTP {response.status}")
                    return
                # Save the file asynchronously
                content = await response.read()
        if content is not None:
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(content)
                if os.path.exists(save_path):
                    os.replace(temp_file.name, save_path) # overwrite
                    print(f"`hosts` file overwritten: {save_path}")
                else:
                    shutil.move(temp_file.name, save_path) # New move
                    print(f"`hosts` file moved to: {save_path}")

    except Exception as e:
        print(f"Error downloading `hosts` file: {e}")

class BwSession:
    def __init__(self,session_id:str, server_addr:str, client_addr:str|None, *, dir:str, hostsfile:str, Pool:ThreadPoolExecutor, lock:asyncio.Lock):
        self.session_id:str = session_id
        self.server_addr:str = server_addr
        self.client_addr:str|None = client_addr
        self.last_access:datetime = datetime.now()
        self.WorkDir:str = dir
        self.hostsfile:str = hostsfile
        self.Pool:ThreadPoolExecutor = Pool
        self._lock:asyncio.Lock = lock
        self.geometry = "1024x900"
        self.vnc_proc:subprocess.Popen|None = None
        self.chrome_process:subprocess.Popen|None = None
        self.display_num:int = 0
        self.vnc_port:int = 0
        self.ws_port:int = 0
        self.cdp_port:int = 0
        # setting
        self._operator_llm:LLM = LLM.Gemini20Flash
        self._planner_llm:LLM|None = None
        # Add attributes for task management
        self._n_tasks:int = 0
        self._task_expand:bool = False
        self.task:BwTask|BwResearchTask|None = None
        self.message_queue: Queue[tuple[int,int,int,int,str,str,str|None]] = Queue()
        self.current_future: Future|None = None

    def touch(self):
        self.last_access:datetime = datetime.now()

    def _write_msg(self,msg):
        self._write_msg4( self._n_tasks,0,0,0,"",msg,None)

    def _write_msg4(self,n_task:int,n_agent:int,n_step:int,n_act:int,header:str,msg,progress:str|None):
        self.touch()
        if isinstance(msg,dict|list):
            msgstr = json.dumps(msg,ensure_ascii=False)
        else:
            msgstr = str(msg)
        self.message_queue.put( (n_task,n_agent,n_step,n_act,header,msgstr,progress) )

    async def get_msg(self,*,timeout:float=1.0) ->tuple[int,int,int,int,str|None,str|None,str|None]:
        break_time = time.time() + max(0, timeout)
        while True:
            try:
                self.touch()
                return self.message_queue.get_nowait()
            except Empty as ex:
                now = time.time()
                if now<break_time:
                    await asyncio.sleep(0.2)
                    continue
                return (0,0,0,0,None,None,None)

    def is_vnc_running(self) -> int:
        return self.display_num if self.display_num>0 and is_proc(self.vnc_proc) else 0

    def is_websockify_running(self) -> int:
        return self.ws_port if self.ws_port>0 and is_proc(self.vnc_proc) else 0

    def is_chrome_running(self) -> int:
        return self.cdp_port if self.cdp_port>0 and is_proc(self.chrome_process) else 0

    def is_ready(self) -> bool:
        return self.is_vnc_running()>0 and self.is_chrome_running()>0

    def is_task(self) ->int:
        if self.current_future and self.current_future.running():
            return 1
        else:
            return 0

    def get_status(self) ->dict:
        self.touch()
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
                raise CanNotStartException(f"Port number {port} was not enabled")
            await asyncio.sleep(.2)

    async def setup_vnc_server(self) -> None:
        """Set up a VNC server and return the hostname and port"""
        if is_proc( self.vnc_proc ):
            return

        self.vnc_proc = None
        self.display_num = 0
        self.vnc_port = 0
        self.ws_port = 0

        await stop_proc(self.vnc_proc)

        vnc_proc:subprocess.Popen|None = None
        try:
            # Start a new VNC server (using a port in the 5900 range)
            display_num,vnc_port = find_available_display()
            # Start websockify (websockify uses 5900, VNC uses 6900)
            ws_port = find_ws_port()
            
            script_path = str(files('buweb.scripts').joinpath('start_vnc.sh'))
            if not os.access(script_path, os.X_OK):
                print(f"Error: {script_path} is not executable.")
            vnc_proc = subprocess.Popen( [
                        script_path,
                        "--display", str(display_num),
                        "--geometry", str(self.geometry),
                        "--rfbport", str(vnc_port),
                        "--wsport", str(ws_port)
                    ], cwd=self.WorkDir, stderr=subprocess.DEVNULL)
            # Wait for the VNC server to start
            await self.wait_port( vnc_proc, vnc_port, 10.0)
            # Wait for websockify to start
            await self.wait_port(vnc_proc,ws_port,10.0)
            if vnc_proc.poll() is not None:
                raise CanNotStartException("Xvnc could not be started")
            
            logger.info(f"[{self.session_id}] Started Xvnc pid:{vnc_proc.pid} :{display_num} port:{vnc_port} port:{ws_port}")
            self.vnc_proc = vnc_proc
            self.display_num = display_num
            self.vnc_port = vnc_port
            self.ws_port = ws_port
            await asyncio.sleep(0.5)

        except Exception as ex:
            await stop_proc(vnc_proc)
            raise ex

    async def launch_chrome(self) -> None:
        """Launch Chrome"""
        if is_proc( self.chrome_process ):
            return
        self.chrome_process = None
        self.cdp_port = 0
        chrome_process:subprocess.Popen|None = None
        try:
            cdp_port = find_cdn_port()
            prof = f"{self.WorkDir}/.config/google-chrome/Default"
            os.makedirs(prof,exist_ok=True)
            script_path = str(files('buweb.scripts').joinpath('start_browser.sh'))
            if not os.access(script_path, os.X_OK):
                print(f"Error: {script_path} is not executable.")
            bcmd=[ script_path,
                "--display", str(self.display_num),
                "--workdir", str(self.WorkDir),
                "--cdpport", str(cdp_port),
            ]
            if os.path.exists(self.hostsfile):
                bcmd.extend( ["--hosts",self.hostsfile])
            chrome_process = subprocess.Popen( bcmd, cwd=self.WorkDir, stdout=subprocess.DEVNULL )
            await self.wait_port(chrome_process,cdp_port,30.0)
            if chrome_process.poll() is not None:
                raise CanNotStartException("google-chrome could not be started")
            self.chrome_process = chrome_process
            self.cdp_port = cdp_port
        except Exception as ex:
            await stop_proc(chrome_process)
            raise ex

    async def start_browser(self) ->dict:
        try:
            self.touch()
            await self.setup_vnc_server()
            if is_proc(self.vnc_proc):
                await self.launch_chrome()
        except CanNotStartException as ex:
            logger.warning(f"[{self.session_id}] {str(ex)}")
        except Exception as ex:
            logger.exception(f"[{self.session_id}] {str(ex)}")
        return self.get_status()

    async def start_task(self, mode:int, task_info: str, llm:LLM, planner_llm:LLM|None, llm_cache:BaseCache|None, trans:Translate, sensitive_data:dict[str,str]|None) -> None:
        """Start task"""
        self.touch()
        if self.task is not None or self.current_future is not None:
            raise RuntimeError("Task is already running")
        else:
            self.current_future = self.Pool.submit(self._start_task, mode, task_info, llm, planner_llm, llm_cache, trans, sensitive_data )

    def _start_task(self, mode:int, prompt: str, llm:LLM, planner_llm:LLM|None,  llm_cache:BaseCache|None, trans:Translate, sensitive_data:dict[str,str]|None ) ->None:
        #loop = asyncio.get_event_loop()
        #loop.run_until_complete(self._run_task(mode, prompt, llm, planner_llm, llm_cache, sensitive_data))
        asyncio.run(self._run_task(mode, prompt, llm, planner_llm, llm_cache, trans, sensitive_data))

    async def _run_task(self, mode:int, prompt: str, llm:LLM, planner_llm:LLM|None,  llm_cache:BaseCache|None, trans:Translate, sensitive_data:dict[str,str]|None) ->None:
        self._n_tasks+=1
        buw:BuwWriter = BuwWriter( n_task=self._n_tasks, writer=self._write_msg4, trans=trans )
        try:
            self.touch()
            await buw.start_global_task(prompt)
            async with self._lock:
                await self.setup_vnc_server()
                await self.launch_chrome()
            if mode==1:
                self.task = BwResearchTask( dir=self.WorkDir,
                                llm_cache=llm_cache, llm=llm, plan_llm=planner_llm,
                                cdp_port=self.cdp_port,
                                sensitive_data=sensitive_data,
                                writer=buw)
            else:
                self.task = BwTask( dir=self.WorkDir,
                                llm_cache=llm_cache, llm=llm, plan_llm=planner_llm,
                                cdp_port=self.cdp_port,
                                sensitive_data=sensitive_data,
                                writer=buw)
            await self.task.start(prompt)
            await self.task.stop()
        except CanNotStartException as ex:
            logger.warning(f"[{self.session_id}] {str(ex)}")
            await buw.done_global_task(str(ex))
        except Exception as ex:
            logger.exception(f"[{self.session_id}] {str(ex)}")
            await buw.done_global_task(str(ex))
        finally:
            self.current_future = None
            self.task = None
            await buw.done_global_task()

    async def cancel_task(self) -> dict:
        """Cancel task"""
        try:
            future:Future|None = self.current_future
            if future is not None:
                while future.running():
                    if self.task is not None:
                        await self.task.stop()
                    await asyncio.sleep(0.5)
                    future.cancel()
        except:
            pass
        return self.get_status()

    async def stop_browser(self) ->dict:
        async with self._lock:
            try:
                logger.info(f"[{self.session_id}] stop_cancel_task")
                # Cancel task
                await self.cancel_task()
                
                logger.info(f"[{self.session_id}] stop_browser")
                await stop_proc( self.chrome_process )
                self.chrome_process = None
                self.cdp_port = 0
                logger.info(f"[{self.session_id}] stop_vnc")
                await stop_proc( self.vnc_proc )
                logger.info(f"[{self.session_id}] stop_kill")
                self.vnc_proc = None
                # Kill remaining processes
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
                logger.exception(f"[{self.session_id}] Error occurred while stopping VNC server: {str(e)}")
        return self.get_status()

    async def store_file(self, file_path:str, data:bytes) -> None:
        """Save file"""
        store_path = os.path.join(self.WorkDir, file_path)
        with open(store_path, "wb") as f:
            f.write(data)

    async def cleanup(self) -> None:
        """Clean up resources"""
        await self.stop_browser()
        if self.task:
            await self.task.stop()
        try:
            shutil.rmtree(self.WorkDir)
        except Exception as e:
            logger.exception(f"[{self.session_id}] Error while stopping: {str(e)}")

# Dictionary to store session data
class SessionStore:
    def __init__(self, *, max_sessions:int=3, dir:str="tmp/sessions", Pool:ThreadPoolExecutor|None=None):
        self._lock = asyncio.Lock()
        self._connect:int = 0
        self._max_sessions:int = max_sessions
        self.sessions: dict[str, BwSession] = {}
        self.SessionsDir:str = os.path.abspath(dir)
        os.makedirs(self.SessionsDir,exist_ok=True)
        self.hostsfile:str = os.path.join(self.SessionsDir,'hosts.adblock')
        self.Pool:ThreadPoolExecutor = Pool if isinstance(Pool,ThreadPoolExecutor) else ThreadPoolExecutor()
        self._lock2:asyncio.Lock = asyncio.Lock()
        self.cleanup_interval:timedelta = timedelta(minutes=30)
        self.session_timeout:timedelta = timedelta(hours=2)
        self._last_cleanup:datetime = datetime.now()
        self._sweeper_task:Task|None = None
        self._llm_cache_path:str = os.path.join(self.SessionsDir,'langchain_cache.db')
        self._llm_cache:BaseCache = SQLiteCache(self._llm_cache_path)
        self._trans:Translate = Translate('ja', os.path.join(self.SessionsDir,'translate_cache.json'))
        # setting
        self._operator_llm:LLM = LLM.Gemini20Flash
        self._planner_llm:LLM|None = None

    async def _start_sweeper(self):
        if self._sweeper_task is None:
            self._sweeper_task = asyncio.create_task(self._sweeper_loop())

    async def _sweeper_loop(self):
        try:
            logger.info("start sweeper")
            while True:
                # Update the hosts file for ad blocking
                now = time.time()
                last_mod_sec:float = os.path.getmtime(self.hostsfile) if os.path.exists(self.hostsfile) else 0.0
                if (now-last_mod_sec)>3600.0:
                    await download_hosts_file_async(self.hostsfile)
                # Clean up the session
                await self.cleanup_old_sessions()
                if len(self.sessions)==0:
                    self._sweeper_task = None
                    return
                await asyncio.sleep(2.0)
        except:
            logger.exception("error in sweeper")
        finally:
            logger.info("end sweeper")
            self._sweeper_task = None

    async def cleanup_old_sessions(self):
        """Clean up old sessions"""
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

    async def incr(self):
        async with self._lock:
            self._connect+=1
    async def decr(self):
        async with self._lock:
            self._connect-=1

    async def get_status(self) ->tuple[int,int,int]:
        async with self._lock:
            return self._connect, len(self.sessions), self._max_sessions

    async def get(self, session_id: str|None) -> BwSession | None:
        """Get the session and update the timestamp"""
        if session_id and session_id in self.sessions:
            session = self.sessions[session_id]
            session.touch()
            return session
        return None

    async def create(self, server_addr:str, client_addr:str|None ) -> BwSession|None:
        "Create a new session"
        if len(self.sessions)>=self._max_sessions:
            return None
        while True:
            session_id = session_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=8))
            if session_id not in self.sessions:
                break
        workdir = os.path.join( self.SessionsDir, f"session_{session_id}")
        logger.info(f"[{session_id}] create session")
        os.makedirs(workdir,exist_ok=False)
        session = BwSession(session_id, server_addr=server_addr, client_addr=client_addr, dir=workdir, hostsfile=self.hostsfile, Pool=self.Pool, lock=self._lock2)
        self.setup_session(session)
        self.sessions[session_id] = session
        await self._start_sweeper()
        return session

    async def remove(self, session_id: str) -> None:
        """Delete session"""
        if session_id in self.sessions:
            logger.info(f"[{session_id}] remove session")
            session = self.sessions[session_id]
            await session.cleanup()
            del self.sessions[session_id]

    async def cleanup_all(self):
        try:
            self.Pool.shutdown(wait=True,cancel_futures=True)
        except:
            pass
        for session_id in list(self.sessions.keys()):
            await self.remove(session_id)
