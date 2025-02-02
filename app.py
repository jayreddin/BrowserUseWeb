#!/usr/bin/env python3
import os,sys,shutil
import asyncio
from flask import Flask, jsonify, send_from_directory, Response, request, make_response
from concurrent.futures import ThreadPoolExecutor
import traceback

import signal
from session import SessionStore, BwSession

Pool:ThreadPoolExecutor = ThreadPoolExecutor(20)
TempHome="./tmp/home"
novncdir="libs/noVNC-1.5.0"

session_store = SessionStore( TempHome=TempHome, novncdir=novncdir, Pool=Pool )

def cleanup_sessions():
    print("### CLEANUP SESSIONS ###")
    # 全セッションのクリーンアップ
    if session_store:
        for session_id in list(session_store.sessions.keys()):
            asyncio.run( session_store.remove(session_id) )

app = Flask(__name__)

@app.route('/')
async def index():
    try:
        client_addr = request.remote_addr
        server_addr = request.host.split(':')[0]
        session_id = request.cookies.get('session_id')
        ses = session_store.get(session_id)
        resp = make_response(send_from_directory('static', 'index.html'))
        if ses is None:
            ses = session_store.create(session_id,client_addr)
            # セキュリティ強化のためのクッキー設定
            resp.set_cookie(
                'session_id',
                ses.session_id,
                httponly=True,  # JavaScriptからのアクセスを防ぐ
                samesite='Strict', # クロスサイトリクエストを防ぐ   
                max_age=session_store.session_timeout    # 2時間で有効期限切れ
            )
        return resp
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

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
            return jsonify({'status': 'error', 'message': 'unauth'}), 401

        if api=='start':
            await ses.setup_browser()
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
            await ses.start_task(task)
            return jsonify({'status': 'success'})
        elif api=='status':
            return jsonify({
                'sv': server_addr,
                'vnc': ses.is_vnc_running(),
                'ws': ses.is_websockify_running(),
                'br': ses.is_chrome_running(),
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
        return jsonify({'status': 'error', 'message': 'invalid api name'}), 404

    except Exception as e:
        traceback.print_exc()
        return jsonify({'status': 'error','message': str(e)}), 500
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