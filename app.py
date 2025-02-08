#!/usr/bin/env python3
import os,sys,shutil
os.environ["ANONYMIZED_TELEMETRY"] = "false"
import asyncio
from queue import Empty
from flask import Flask, jsonify, send_from_directory, Response, request, make_response, abort
from concurrent.futures import ThreadPoolExecutor
import traceback
from dotenv import load_dotenv
import signal
import time
import json
from session import SessionStore, BwSession
from browser_task import LLM

from logging import Logger,getLogger
logger:Logger = getLogger(__name__)

Pool:ThreadPoolExecutor = ThreadPoolExecutor(20)
SessionsDir="./tmp/sessions"
novncdir="third_party/noVNC-1.5.0"

session_store = SessionStore( dir=SessionsDir, Pool=Pool )

def cleanup_sessions():
    print("### CLEANUP SESSIONS ###")
    # 全セッションのクリーンアップ
    if session_store:
        asyncio.run( session_store.cleanup_all() )

app = Flask(__name__)

@app.route('/')
async def index():
    return make_response(send_from_directory('static', 'index.html'))

@app.route('/config.html')
async def config():
    return make_response(send_from_directory('static', 'config.html'))

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

@app.route('/api/llm_list')
async def llm_list():
    """LLMの一覧を返す"""
    try:
        llm_list = [{"name": llm.name, "value": llm._full_name} for llm in LLM]
        return jsonify({
            'status': 'success',
            'llm_list': llm_list
        })
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)}), 500

@app.route('/api/config', methods=['GET','POST'])
async def config_api():
    try:
        if request.method == 'POST':
            data = request.get_json()
            operator = data.get('operator_llm')
            planner = data.get('planner_llm')
            max_sessions = data.get('max_sessions')
            
            # nameからLLMを取得
            operator_llm = LLM[operator]
            planner_llm = LLM[planner] if planner else None
            max_sessions = int(max_sessions)
            session_store.configure(operator_llm, planner_llm, max_sessions)
        # 現在のLLM設定を返す
        current_connections,current_sessions,max_sessions = session_store.get_status()
        return jsonify({
            'status': 'success',
            'operator_llm': session_store._operator_llm.name,
            'planner_llm': session_store._planner_llm.name if session_store._planner_llm else None,
            'current_conneections': current_connections,
            'current_sessions': current_sessions,
            'max_sessions': max_sessions,
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error','msg': str(e)}), 500

@app.route('/api/<path:api>', methods=['GET','POST'])
async def service_api(api):
    try:
        client_addr = request.remote_addr
        server_addr = request.host.split(':')[0]
        session_id = request.headers.get("X-Session-ID")
        ses:BwSession|None = await session_store.get(session_id)
        # sessionの場合
        if api == 'session':
            if ses is not None:
                return jsonify({'status': 'error', 'msg': 'unauth'}), 401
            def sesgenerate():
                ses = None
                try:
                    session_store.incr()
                    ses = asyncio.run( session_store.create(server_addr,client_addr))
                    if ses is None:
                        res = { 'status': 'success', 'msg': '接続数制限中' }
                        yield f"data: {json.dumps(res, ensure_ascii=False)}\n\n"
                        while ses is None:
                            time.sleep(1.0)
                            ses = asyncio.run( session_store.create(server_addr,client_addr))

                    res = ses.get_status()
                    res['msg'] = '接続完了'
                    yield f"data: {json.dumps(res, ensure_ascii=False)}\n\n"

                    while ses is not None:
                        try:
                            try:
                                msg = ses.message_queue.get(timeout=1.0)
                            except Empty:
                                msg = None
                            ses.touch()
                            res = ses.get_status()
                            if msg is not None:
                                res['msg'] = msg
                            yield f"data: {json.dumps(res, ensure_ascii=False)}\n\n"
                        except:
                            break
                finally:
                    if ses is not None:
                        asyncio.run( session_store.remove(ses.session_id) )
                    session_store.decr()
            return Response(sesgenerate(), mimetype='text/event-stream')   
  
        # session意外の場合
        if ses is None:
            return jsonify({'status': 'error', 'msg': 'unauth'}), 401

        if api=='browser_start':
            res = await ses.start_browser()
            return jsonify(res)

        elif api=='task_start':
            data = request.get_json()
            task = data.get('task', '')
            expand:bool = data.get('expand','') == 'true'
            msg = None
            if task:
                await ses.start_task(task, session_store._operator_llm, session_store._planner_llm, session_store._llm_cache)
            else:
                msg = 'タスクが指定されていません'
            res = ses.get_status()
            if msg:
                res['msg'] = msg
            return jsonify(res)

        elif api=='task_stop':
            res = await ses.cancel_task()
            return jsonify(res)

        elif api=='browser_stop':
            res = await ses.stop_browser()
            return jsonify(res)

        return jsonify({'status': 'error', 'msg': 'invalid api name'}), 404

    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error','msg': str(e)}), 500
    finally:
        try:
            current_loop = asyncio.get_running_loop()
            while True:
                tasks = {task for task in asyncio.all_tasks(loop=current_loop) if task is not asyncio.current_task()}
                if not tasks:
                    break
                await asyncio.sleep(0.1)
        except:
            pass

def main():
    # .envファイルをロード
    for envfile in ('config.env','.env'):
        try:
            if os.path.exists(envfile):
                load_dotenv(envfile)
        except:
            pass
    # シグナルハンドラ
    def sig_handler(signum, frame) -> None:
        sys.exit(1)
    signal.signal(signal.SIGTERM, sig_handler)

    try:
        # flaskサーバ起動
        app.run(host='0.0.0.0', port=5000, threaded=True)
    finally:
        # 終了処理
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        cleanup_sessions()
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)

if __name__ == '__main__':
    main()
