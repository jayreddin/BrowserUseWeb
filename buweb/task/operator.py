import os
os.environ["ANONYMIZED_TELEMETRY"] = "false"
import json
from datetime import datetime
import time
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from pydantic import SecretStr
from enum import Enum
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from langchain_core.messages import BaseMessage
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.caches import BaseCache
from langchain_core.caches import InMemoryCache
from langchain_community.cache import SQLiteCache
import browser_use.controller.service
from browser_use import ActionModel, Agent, SystemPrompt, Controller,Browser, BrowserConfig
from browser_use.agent.prompts import AgentMessagePrompt
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.browser.views import BrowserError, BrowserState, BrowserStateHistory
from browser_use.agent.views import ActionResult, AgentOutput, AgentHistoryList, AgentStepInfo
#from browser_use.controller.views import ScrollAction
from browser_use.dom.service import DomService
from browser_use.dom.views import DOMElementNode, SelectorMap
from playwright.async_api import Page
import asyncio
from typing import Callable, Optional, Dict,Literal, Type
from pydantic import BaseModel
from logging import Logger,getLogger, ERROR as LogError
from dotenv import load_dotenv

from buweb.agent.buw_agent import BuwWriter, BuwAgent
from buweb.controller.buw_controller import BwController
from buweb.model.model import LLM, create_model

logger:Logger = getLogger(__name__)

os.environ["ANONYMIZED_TELEMETRY"] = "false"

class BwTask:

    def __init__(self,*, dir:str,
                llm_cache:BaseCache|None=None, llm:LLM=LLM.Gpt4oMini, plan_llm:LLM|None=None,
                chrome_instance_path:str|None=None, cdp_port:int|None=None, trace_path:str|None=None,
                sensitive_data:dict[str,str]|None=None,
                writer:BuwWriter|None=None):
        self._work_dir:str = dir
        if llm_cache is None:
            llm_cache = SQLiteCache( os.path.join(dir,'langchain_cache.db') )
        self._operator_llm:LLM = llm
        self._plan_llm:LLM|None = plan_llm
        self._llm_cache:BaseCache = llm_cache
        self._writer:BuwWriter = writer if writer is not None else BuwWriter()
        self.cdp_port:int|None = cdp_port
        bw_context_config:BrowserContextConfig = BrowserContextConfig(
            maximum_wait_page_load_time=1.2,
            viewport_expansion=0,
            browser_window_size={'width':1366,'height':768},
        )
        if isinstance(cdp_port,int) and cdp_port>0:
            bw_config = BrowserConfig(
                cdp_url=f"http://127.0.0.1:{cdp_port}"
            )
        else:
            p = None
            for p in [ chrome_instance_path, "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/opt/google/chrome/google-chrome" ]:
                if p and os.path.exists( p ):
                    chrome_instance_path = p
                    break
            if p is None:
                raise ValueError("")
            bw_config = BrowserConfig(
                #chrome_instance_path=chrome_instance_path,
                #extra_chromium_args=[str(self.display_number)],
            )

        self._browser:Browser = Browser( bw_config )
        self._browser_context:BrowserContext = BrowserContext( self._browser, bw_context_config)
        self._agent:BuwAgent|None = None
        self._sensitive_data=sensitive_data

    def logPrint(self,msg):
        if self._writer is not None:
            self._writer.print(msg=msg)
        else:
            logger.info( f"##logPrint {msg}")

    def logPrintX(self, *, header:str="", msg:str="", progress:str|None=None):
        if self._writer is not None:
            self._writer.print( header=header,msg=msg,progress=progress)
        else:
            logger.info( f"##logPrint {msg}")

    async def start(self,task:str):

        alog=getLogger("browser_use")
        alog.setLevel(LogError)
        now = datetime.now()
        now_datetime = now.strftime("%A, %Y-%m-%d %H:%M")

        if self._plan_llm is not None:
            self.logPrint(f"planner:{self._plan_llm._full_name}")
        self.logPrint(f"operator:{self._operator_llm._full_name}")
        x_extractor = LLM.get_lite_model(self._operator_llm)
        self.logPrint(f"extractor:{x_extractor._full_name}")
        llm_cache:BaseCache = self._llm_cache
        operator_llm:BaseChatModel = create_model(self._operator_llm, cache=llm_cache)
        test_res = await operator_llm.ainvoke(f"{now_datetime}動作テストです。正常稼働ならYesを返信して。")
        extraction_llm:BaseChatModel = create_model(x_extractor, cache=llm_cache)
        planner_llm:BaseChatModel|None = create_model(self._plan_llm, cache=llm_cache) if self._plan_llm is not None else None

        plan_text:str|None = None
        if planner_llm is not None:
            pre_prompt = [
                "現在時刻:{now_datetime}",
                "ブラウザを使って以下のタスクを実行するために、目的、ブラウザで収集すべき情報、手順、ゴールを考えて、簡潔で短い文章で実行プランを出力して。",
                "---与えられたタスク---",
                "```",
                task,
                "```",
            ]
            pre_result:BaseMessage = await planner_llm.ainvoke( "\n".join(pre_prompt))
            if isinstance(pre_result.content,str):
                plan_text = pre_result.content
                #self.logPrint(plan_text)

        web_task = f"# 現在時刻: {now_datetime}\n\n# 与えられたタスク:\n{task}"
        if plan_text is not None:
            web_task += f"\n\n実行プラン:\n{plan_text}"
        web_task += f"\n\n# 作業手順\n与えられたタスクと設定したゴールを満たしたか考えながら実行プランにそって実行して下さい。必要に応じて前の作業にもどったりプランを修正することも可能です。"

        #---------------------------------
        #br_context = await self.get_browser_context()
        cb = None
        if self._writer is not None:
            cb = self._writer.action
        wcnt = BwController( callback=cb)

        final_str:str|None = None
        try:
            self._writer._agent_task = task
            self._agent = BuwAgent(
                task=web_task,
                llm=operator_llm, page_extraction_llm=extraction_llm, planner_llm=planner_llm, planner_interval=1,
                use_vision=False,
                controller=wcnt,
                browser=self._browser,
                browser_context=self._browser_context,
                sensitive_data=self._sensitive_data,
            )
            result: AgentHistoryList = await self._agent.run(wr=self._writer)
            if result.is_done():
                final_str = result.final_result()
        except Exception as ex:
            self.logPrint("")
            self.logPrint(f"停止しました {str(ex)}")
        finally:
            self._agent = None
        #---------------------------------
        if final_str:
            post_llm = create_model(LLM.Gemini20Flash) # ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
            report_task = f"# 現在時刻: {now_datetime}\n\n# 与えられたタスク:\n{task}"
            if plan_text is not None:
                report_task += f"\n\n# 実行プラン:\n{plan_text}"
            report_task += f"\n\n# 実行結果\n{final_str}\n\n# 実行結果の内容を日本語でレポートしてください。"
            post_result:BaseMessage = await post_llm.ainvoke( report_task )
            if isinstance(post_result.content,str):
                report = post_result.content
            else:
                report = final_str
            self.logPrint("---------------------------------")
            self.logPrint(report)
    
    async def stop(self):
        try:
            if self._agent is not None:
                self._agent.stop()
        except:
            pass