import sys,os
sys.path.append('.')
os.environ["ANONYMIZED_TELEMETRY"] = "false"
import json
from datetime import datetime
import time
from enum import Enum
from playwright.async_api import Page
import asyncio
from typing import Callable, Optional, Dict,Literal, Type
from pydantic import BaseModel
from logging import Logger,getLogger
from dotenv import load_dotenv

from buweb.model.model import LLM
from buweb.task.operator import BwTask

logger:Logger = getLogger(__name__)

os.environ["ANONYMIZED_TELEMETRY"] = "false"

async def main():
    # from session import SessionStore, BwSession
    if os.path.exists('config.env'):
        load_dotenv('config.env')
    task="キャトルアイサイエンス株式会社の会社概要をしらべて"
    #task="192.168.1.200にmaeda/maeda0501でログインして、通常モードに切り替えて、会議室予約に、「1/30 テストですよ 参加者前田」を追加する。"
    #task="Amazonで、格安の2.5inch HDDを探して製品URLをリストアップしてください。"
    workdir = os.path.abspath("tmp/testrun")
    os.makedirs(workdir,exist_ok=True)
    btask = BwTask(dir=workdir,llm=LLM.Gemini20Flash)
    await btask.start(task)
    await btask.stop()
    print("done")

async def test_hilight():
    """ハイライトが遅いのかを確認するテスト"""
    workdir = os.path.abspath("tmp/testrun")
    os.makedirs(workdir,exist_ok=True)
    btask = BwTask(dir=workdir,llm=LLM.Gemini20Flash)

    browser_context = btask._browser_context
    page = await browser_context.get_current_page()
    await page.goto("https://www.amazon.co.jp/")
    await page.wait_for_load_state()
    # ---
    session = await browser_context.get_session()
    cached_selector_map = session.cached_state.selector_map
    cached_path_hashes = set(e.hash.branch_path_hash for e in cached_selector_map.values())
    print(f"cached_path_hashes:{cached_path_hashes}")
    # ---
    new_state = await browser_context.get_state()
    new_path_hashes = set(e.hash.branch_path_hash for e in new_state.selector_map.values())
    print(f"new_path_hashes:{new_path_hashes}")

    print("done")

async def test_js():
        import json
        """ハイライトが遅いのかを確認するテスト"""
        workdir = os.path.abspath("tmp/testrun")
        os.makedirs(workdir,exist_ok=True)
        btask = BwTask(dir=workdir,llm=LLM.Gemini20Flash)

        browser_context = btask._browser_context
        page:Page = await browser_context.get_current_page()
        await page.goto("https://www.amazon.co.jp/")
        await page.wait_for_load_state()
        # ---
        session = await browser_context.get_session()
        from browser_use.dom.service import DomService
        dom_service = DomService(page)

        focus_element: int = -1
        viewport_expansion = 0
        highlight_elements = True
        # content = await dom_service.get_clickable_elements(
        #     focus_element=focus_element,
        #     viewport_expansion=viewport_expansion,
        #     highlight_elements=highlight_elements,
        # )
        #js_code = resources.read_text('browser_use.dom', 'buildDomTree.js')
        jsfile = 'buildDomTreeCustom.js'
        with open( os.path.join('static',jsfile), 'r', encoding='utf-8') as file:
            js_code = file.read()

        args = {
			'doHighlightElements': highlight_elements,
			'focusHighlightIndex': focus_element,
			'viewportExpansion': viewport_expansion,
		}

        t0 = time.time()
        try:
            eval_page = await page.evaluate(js_code, args)  # This is quite big, so be careful
        except Exception as ex:
            print(f"error: s{str(ex)}")
        t9 = time.time()
        print(f"Time {jsfile} {t9-t0:.3f}(Sec)")

        content_html = await page.content()
        html_file_path = os.path.join("tmp", jsfile.replace('.js','.html'))
        with open(html_file_path, "w", encoding="utf-8") as f:
            f.write(content_html)

        json_file_path = os.path.join("tmp", jsfile.replace('.js','.json'))
        with open(json_file_path, "w", encoding="utf-8") as f:
            json.dump(eval_page, f, ensure_ascii=False, indent=4)

        print(f"Done {json_file_path}")

if __name__ == "__main__":
    asyncio.run(main())
