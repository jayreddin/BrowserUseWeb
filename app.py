#!/usr/bin/env python3
import os,sys,shutil,subprocess
from typing import AsyncIterable
os.environ["ANONYMIZED_TELEMETRY"] = "false"
import asyncio
from quart import Quart, request, jsonify, send_from_directory, Response
from concurrent.futures import ThreadPoolExecutor
import traceback
from dotenv import load_dotenv
import signal
import time
import json

from buweb.service.session import SessionStore, BwSession
from buweb.model.model import LLM

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

app = Quart(__name__)

@app.route('/', defaults={'path': 'index.html'})
@app.route('/<path:path>')
async def style_css(path):
    print(f"REQ:{path}")
    return await send_from_directory('static', path)

@app.route('/novnc/<path:path>')
async def novnc_files(path):
    """noVNCのファイルを提供"""
    return await send_from_directory(novncdir, path)

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
            data = await request.get_json()
            operator = data.get('operator_llm')
            planner = data.get('planner_llm')
            max_sessions = data.get('max_sessions')
            
            # nameからLLMを取得
            operator_llm = LLM[operator]
            planner_llm = LLM[planner] if planner else None
            max_sessions = int(max_sessions)
            session_store.configure(operator_llm, planner_llm, max_sessions)
        # 現在のLLM設定を返す
        current_connections,current_sessions,max_sessions = await session_store.get_status()
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

def compare_dicts(d1, d2):
    if d1.keys() != d2.keys():
        return False
    for key in d1:
        if isinstance(d1[key], dict) and isinstance(d2[key], dict):
            if not compare_dicts(d1[key], d2[key]):
                return False
        else:
            if d1[key] != d2[key]:
                return False
    return True

async def session_stream(server_addr,client_addr) ->AsyncIterable[str]:
    ses = None
    try:
        await session_store.incr()
        ses = await session_store.create(server_addr,client_addr)
        if ses is None:
            res = { 'status': 'success', 'msg': '接続数制限中' }
            yield f"data: {json.dumps(res, ensure_ascii=False)}\n\n"
            while ses is None:
                await asyncio.sleep(1)
                ses = await session_store.create(server_addr,client_addr)

        res = ses.get_status()
        res['msg'] = '接続完了'
        yield f"data: {json.dumps(res, ensure_ascii=False)}\n\n"

        before_res = {}
        before_time = 0.0
        while ses is not None:
            try:
                n_task,n_agent,n_step,n_act,header,msg,progress = await ses.get_msg(timeout=1)
                res = ses.get_status()
                now = time.time()
                if msg is None:
                    if (now-before_time)<10 and compare_dicts(before_res, res):
                        continue
                else:
                    if n_task>0:
                        res['task'] = n_task
                    if n_agent>0:
                        res['agent'] = n_agent
                    if n_step>0:
                        res['step'] = n_step
                    if n_act>0:
                        res['act'] = n_act
                    res['header'] = header
                    res['msg'] = msg
                    res['progress'] = progress
                yield f"data: {json.dumps(res, ensure_ascii=False)}\n\n"
                before_res = res
                before_time = now
            except Exception as ex:
                traceback.print_exc()
                break
    except Exception as ex:
        traceback.print_exc()
    finally:
        if ses is not None:
            await session_store.remove(ses.session_id)
        await session_store.decr()

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
            headers = { "Content-Type": "text/event-stream" }
            ress = Response(session_stream(server_addr,client_addr), headers=headers, mimetype='text/event-stream')   
            ress.timeout = None # disable timeout
            return ress
  
        # session意外の場合
        if ses is None:
            return jsonify({'status': 'error', 'msg': 'unauth'}), 401

        if api=='browser_start':
            res = await ses.start_browser()
            return jsonify(res)

        elif api=='task_start':
            data = await request.get_json()
            mode = data.get('mode',0)
            task = data.get('task', '')
            sensitive_data = data.get('sensitive_data', None)
            expand:bool = data.get('expand','') == 'true'
            msg = None
            if task:
                await ses.start_task(mode, task,
                                    session_store._operator_llm, session_store._planner_llm,
                                    session_store._llm_cache, session_store._trans,
                                    sensitive_data)
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

        elif api=='store_file':
            upfiles = await request.files
            if 'file' not in upfiles:
                return jsonify({'status': 'error', 'msg': 'No file part'})
            
            file = upfiles['file']
            if file.filename is None or file.filename == '':
                return jsonify({'status': 'error', 'msg': 'No selected file'})
            
            try:
                # ファイルの内容を読み込む
                content = file.read()
                # ファイルを保存
                await ses.store_file(file.filename, content)
                return jsonify({'status': 'success', 'msg': ''})
            except Exception as e:
                return jsonify({'status': 'error', 'msg': str(e)})

        return jsonify({'status': 'error', 'msg': 'invalid api name'}), 404

    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error','msg': str(e)}), 500
    finally:
        try:
            pass
        except:
            pass

def main():
    # 環境チェック
    check_result = subprocess.run(['bash', 'buweb/scripts/check_environment.sh'], 
                                capture_output=True, text=True)
    
    # 常に標準出力を表示
    if check_result.stdout:
        print(check_result.stdout.strip())
    if check_result.stderr:
        print(check_result.stderr.strip(), file=sys.stderr)
    
    # エラーがある場合は終了
    if check_result.returncode != 0:
        sys.exit(1)

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
        # サーバ起動
        app.run(host='0.0.0.0', port=5000, debug=False )
    finally:
        # 終了処理
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        cleanup_sessions()
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)

if __name__ == '__main__':
    main()
