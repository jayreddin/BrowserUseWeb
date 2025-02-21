import sys, os, asyncio
os.environ["ANONYMIZED_TELEMETRY"] = "false"
sys.path.append('.')
from datetime import datetime
from shutil import rmtree

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.caches import BaseCache
from langchain_community.cache import SQLiteCache


# from browser_use.controller.service import Controller
from buweb.Research.task.deep_research import deep_research


async def test_run():
    from dotenv import load_dotenv
    load_dotenv('config.env')
    from buweb.model.model import LLM, create_model
    tmpdir = os.path.abspath("tmp/deep_research")
    os.makedirs(tmpdir,exist_ok=True)

    llm_cache_path:str = os.path.join(tmpdir,'langchain_cache.db')
    llm_cache:BaseCache = SQLiteCache(llm_cache_path)

    task_id = 'testrun' # str(uuid4())
    work_dir = os.path.join( tmpdir,f"{task_id}")
    if os.path.exists(work_dir):
        rmtree(work_dir,ignore_errors=True)
    os.makedirs(work_dir, exist_ok=True)

    #limitter = CustomRateLimiter( requests_per_minute=10, requests_per_day=1500, record_file_path='tmp/limit.json')

    llm:LLM = LLM.Gemini20Flash
    op_llm:BaseChatModel = create_model(llm, cache=llm_cache)
    task = "調査の動作テストをしてください。ブラウザで何かを検索して、動作テスト結果をレポートして。"
    task = "write a report of browser-use of 'https://github.com/browser-use/browser-use'"
    task = "今週の天気のニュースをまとめて"
    report = await deep_research( task, op_llm, save_dir=work_dir, llm_cache=llm_cache)
    print("------------------------")
    print(report)

if __name__ == "__main__":
    asyncio.run(test_run())