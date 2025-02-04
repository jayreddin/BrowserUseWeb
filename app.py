#!/usr/bin/env python3
import os,sys,shutil
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
        session_id = request.headers.get("X-Session-ID")
        ses:BwSession|None = await session_store.get(session_id)
        # sessionの場合
        if api == 'session':
            if ses is not None:
                return jsonify({'status': 'error', 'msg': 'unauth'}), 401
            def sesgenerate():
                ses = None
                try:
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
                await ses.start_task(task,expand)
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