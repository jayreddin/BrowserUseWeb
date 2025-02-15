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
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.rate_limiters import BaseRateLimiter, InMemoryRateLimiter
from google.api_core.exceptions import ResourceExhausted as GoogleResourceExhausted
from openai import RateLimitError as OpenaiRateLimitError

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
from logging import Logger,getLogger
from dotenv import load_dotenv

from buweb.agent.buw_agent import BuwAgent
from buweb.browser.buw_browser import BwBrowserContext
from buweb.controller.buw_controller import BwController

logger:Logger = getLogger(__name__)

os.environ["ANONYMIZED_TELEMETRY"] = "false"

class CustomRateLimiter(BaseRateLimiter):
    def __init__(self, requests_per_minute:int, requests_per_day:int, record_file_path:str|None ):
        self.requests_per_minute = requests_per_minute
        self.requests_per_day = requests_per_day
        self.requests_in_day:int = 0
        self.requests_in_minute:list[float] = []
        dt = datetime.now().strftime("%Y-%m-%d")
        self.current_date = dt
        self.record_file_path = record_file_path
        if record_file_path and os.path.exists(record_file_path):
            with open(record_file_path, "r") as fr:
                aaa = json.load(fr)
                b = aaa.get(f'requests_in_{dt}',0.0)
                if isinstance(b,int|float):
                    self.requests_in_day = int(b)
                c = aaa.get('requests_in_minute',[])
                if isinstance(c,list):
                    self.requests_in_minute = c
    def _save(self,dt):
        if self.record_file_path:
            with open(self.record_file_path, "w") as fr:
                json.dump( {f'requests_in_{dt}': self.requests_in_day, 'requests_in_minute': self.requests_in_minute},fr)

    def _can_acquire(self) ->bool:
        dt = datetime.now().strftime("%Y-%m-%d")
        if dt != self.current_date:
            self.requests_in_day = 0
            self.current_date = dt
        if self.requests_in_day>=self.requests_per_day:
            print(f"RateLimit: requests per day {self.requests_in_day}/{self.requests_per_day}")
            return False
        now = time.time()
        while len(self.requests_in_minute)>0 and now-self.requests_in_minute[0]>60.0:
            print(f"RateLimit: RPM {len(self.requests_in_minute)}/{self.requests_per_minute}")
            self.requests_in_minute.pop(0)
        if len(self.requests_in_minute)>=self.requests_per_minute:
            return False
        self.requests_in_day += 1
        self.requests_in_minute.append(now)
        self._save(dt)
        return True

    def acquire(self, *, blocking: bool = True) -> bool:
        if blocking:
            while not self._can_acquire():
                time.sleep(1.0)
            return True
        else:
            return self._can_acquire()

    async def aacquire(self, *, blocking: bool = True) -> bool:
        if blocking:
            while not self._can_acquire():
                await asyncio.sleep(1.0)
            return True
        else:
            return self._can_acquire()

class CustomChatGoogleGenerativeAI(ChatGoogleGenerativeAI):

    def invoke(self,input):
        i=0
        msg:str='abc123'
        while True:
            i+=1
            try:
                return super().invoke(input)
            except GoogleResourceExhausted as ex1:
                exmsg = f"{ex1}"
                if exmsg != msg:
                    print(exmsg)
                    msg=exmsg
                else:
                    print( '*' if i%2==0 else '+',end='')
                if i>=30:
                    raise ex1
                time.sleep(10.0)

    async def ainvoke(self,input):
        i=0
        msg:str='abc123'
        while True:
            i+=1
            try:
                return await super().ainvoke(input)
            except GoogleResourceExhausted as ex1:
                exmsg = f"{ex1}"
                if exmsg != msg:
                    print(exmsg)
                    msg=exmsg
                else:
                    print( '*' if i%2==0 else '+',end='')
                if i>=30:
                    raise ex1
                await asyncio.sleep(10.0)

t128k:int = 128000
t8k:int = 8192
t16k:int = 16384
t32k:int = 32768
t64k:int = 65536
t128k:int = 131072

class LLM(Enum):
    Gpt4o = ( "gpt-4o", 0, t64k )
    Gpt4oMini = ( "gpt-4o-mini", 0, t64k )
    O3Mini = ( "o3-mini", 0, t64k )
    Gemini20Flash = ( "gemini-2.0-flash-exp", 1, t64k )
    Gemini20FlashThink = ( "gemini-2.0-flash-thinking-exp-01-21", 1, t64k )
    Gemini20Pro = ( "gemini-2.0-pro-exp-02-05", 1, t64k )

    Phi3 = ( "phi3:latest", 9, t64k )
    Arrowpro = ( "hawkclaws/datapilot-arrowpro-7b-robinhood:latest", 9, t64k )

    LlamaTranslate = ( "7shi/llama-translate:8b-q4_K_M", 9, t64k )
    DeepSeekV3 = ( "nezahatkorkmaz/deepseek-v3:latest", 9, t64k )
    DeepSeekR1_1B = ( "deepseek-r1:1.5b", 9, t64k )
    DeepSeekR1_cline_tools_1B = ( "tom_himanen/deepseek-r1-roo-cline-tools:1.5b", 9, t64k )
    DeepSeekR1_cline_tools_8B = ( "tom_himanen/deepseek-r1-roo-cline-tools:8b", 9, t64k )
    DeepSeekR1_coder_tools_1B = ( "Mrs_peanutbutt3r/deepseek-r1-coder-tools:1.5b", 9, t64k )
    DeepSeekR1_coder_tools_8B = ( "Mrs_peanutbutt3r/deepseek-r1-coder-tools:7b", 9, t64k )
    DeepSeekR1_tool_call_7B = ( "MFDoom/deepseek-r1-tool-calling:7b", 9, t64k )
    DeepSeekR1_tool_call_1B = ( "MFDoom/deepseek-r1-tool-calling:1.5b", 9, t64k )

    def __init__(self, value: str, grp:int, sz:int):
        self.__value__ = value
        self._full_name:str = value
        self._grp:int = grp
        self._sz:int = sz

    @staticmethod
    def get_lite_model(llm:"LLM") -> "LLM":
        if llm==LLM.Gpt4o or llm==LLM.Gpt4oMini or llm==LLM.O3Mini:
            return LLM.Gpt4oMini
        if llm==LLM.Gemini20Flash or llm==LLM.Gemini20Pro or llm==LLM.Gemini20FlashThink:
            return LLM.Gemini20Flash
        return LLM.Gemini20Flash

    @staticmethod
    def get_llm(name:"str|LLM|None") -> "LLM|None":
        if isinstance(name,LLM) or name is None:
            return name
        for llm in LLM:
            if name==llm.name or name==llm._full_name:
                return llm
        return None

def create_model( model:str|LLM,temperature:float=0.0,cache:BaseCache|None=None) -> BaseChatModel:
    llm = LLM.get_llm(model)
    if llm:
        if llm._grp==0:
            openai_api_key = os.getenv('OPENAI_API_KEY')
            if not openai_api_key:
                raise ValueError('OPENAI_API_KEY is not set')
            return ChatOpenAI(model=llm._full_name, temperature=temperature, cache=cache)
        elif llm._grp==1:
            kw = None
            if os.getenv('GEMINI_API_KEY') is not None:
                kw = SecretStr(os.getenv('GEMINI_API_KEY')) # type: ignore
            elif os.getenv('GOOGLE_API_KEY') is not None:
                kw = SecretStr(os.getenv('GOOGLE_API_KEY')) # type: ignore
            if kw is None:
                raise ValueError('GEMINI_API_KEY or GOOGLE_API_KEY is not set')
            if llm==LLM.Gemini20FlashThink:
                return CustomChatGoogleGenerativeAI(model=llm._full_name, cache=cache, api_key=kw)
            else:
                return CustomChatGoogleGenerativeAI(model=llm._full_name,temperature=temperature, cache=cache, api_key=kw)
        elif llm._grp==9:
            ollama_url = os.getenv('OLLAMA_HOST')
            if not ollama_url:
                raise ValueError('OLLAMA_HOST is not set')
            return ChatOllama(model=llm._full_name, num_ctx=llm._sz, cache=cache)
    raise ValueError(f"Invalid model name: {model}")