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
from browser_use import Agent, SystemPrompt, Controller,Browser, BrowserConfig
from browser_use.agent.prompts import AgentMessagePrompt
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.browser.views import BrowserError, BrowserState, BrowserStateHistory
from browser_use.agent.views import ActionResult, AgentOutput, AgentHistoryList, AgentStepInfo
from browser_use.controller.registry.service import ActionModel
#from browser_use.controller.views import ScrollAction
from browser_use.dom.views import DOMElementNode, SelectorMap
from playwright.async_api import Page
import asyncio
from typing import Callable, Optional, Dict,Literal, Type
from pydantic import BaseModel
from logging import Logger,getLogger,ERROR as LvError
from dotenv import load_dotenv

logger:Logger = getLogger(__name__)

class BuwWriter:
    def __init__(self,n_task:int=0,writer:Callable[[int,int,int,int,str,str|dict,str|None],None]|None=None):
        self._writer:Callable[[int,int,int,int,str,str|dict,str|None],None]|None = writer
        self._global_task:str = ""
        self._n_task:int = n_task
        self._agent_task:str = ""
        self._n_agents:int=0
        self._n_steps:int=0
        self._n_actions:int=0

    def print(self, *, header:str="", msg:str|dict="", progress:str|None=None):
        """
        header: タスク名
        msg: メッセージ
        progress: 進捗 Noneの場合は進捗変更なし
        """
        try:
            timestamp = datetime.now().strftime("%H:%M:%S")
            if self._writer is None:
                index = ""
                if self._n_task>0:
                    index = f"Task:{self._n_task}"
                if self._n_agents>0:
                    index = f"{index} Agent:{self._n_agents}"
                if self._n_steps>0:
                    index = f"{index} Step:{self._n_steps}"
                if self._n_actions>0:
                    index = f"{index} Act:{self._n_actions}"
                print(f"##AgemtPrint {timestamp} {index} {header} {msg}")
            else:
                self._writer(self._n_task, self._n_agents, self._n_steps, self._n_actions, header, msg, progress)
        except Exception as e:
            print(f"##AgemtPrint {e}")

    async def start_global_task(self,global_task:str):
        self._n_agents = 0
        self._n_steps = 0
        self._n_actions = 0
        if self._global_task:
            global_task = self._global_task
        self.print( header=global_task, progress="running...")

    async def start_agent(self,agent_task:str):
        """agentがrun開始したときに呼ばれる"""
        self._n_agents += 1
        self._n_steps = 0
        self._n_actions = 0
        if self._agent_task:
            agent_task = self._agent_task
        self.print( header=agent_task, progress="running..." )

    async def start_plannner(self, n_steps:int):
        self._n_steps = n_steps
        self.print(progress=f"planning...")

    async def done_plannner(self,plan:str|None):
        self.print( msg=f"Plan: {plan}",progress="")

    async def start_get_next_action(self, n_steps:int):
        self._n_steps = n_steps
        self._n_actions = 0
        if self._n_steps>1:
            self.print( progress=f"Evaluate result and get next action")

    async def done_get_next_action(self, state: BrowserState, output: AgentOutput, step: int):
        self._n_actions = 0
        if self._n_steps>1:
            self._n_steps -= 1
            self.print( msg=f'{output.current_state.evaluation_previous_goal}',progress="")
            self._n_steps += 1
        self.print( header=f'{output.current_state.next_goal}',progress="")
        for i, action in enumerate(output.action):
            self._n_actions = i + 1
            headers=[]
            for action_name, params in action.model_dump(exclude_unset=True).items():
                if params is not None and action_name != "done":
                    headers.append(f"{action_name} {params}")
                else:
                    headers.append(f"{action_name}")
            self.print( header=','.join(headers) )
        self._n_actions = 0

    async def action(self,action:ActionModel|ActionResult):
        if isinstance(action,ActionModel):
            await self.start_action(action)
        elif isinstance(action,ActionResult):
            await self.done_action(action)

    async def start_action(self,action:ActionModel):
        self._n_actions += 1
        try:
            for action_name, params in action.model_dump(exclude_unset=True).items():
                if params is None:
                    continue
                self.print( progress="running..." )
        except Exception as e:
            self.print( msg=f"{e}", progress="error")

    async def done_action(self,result:ActionResult):
        content = result.extracted_content
        if content is None or len(content)==0:
            content = ""
            self.print( progress="" )
        else:
            content = f"{content}".replace("\n","\\n").replace("\r","\\r")
            if len(content)>=100:
                content = content[:40]+" ....... " + content[-40:]
            self.print( msg=f"extracted_content:{content}", progress="" )

    async def done_agent(self, history: AgentHistoryList):
        self._agent_task = ""
        self._n_steps = 0
        self._n_actions = 0
        self._n_agents = 0
        self.print(progress="")

    async def done_global_task(self,progress:str=""):
        self._agent_task = ""
        self._global_task = ""
        self._n_agents = 0
        self._n_steps = 0
        self._n_actions = 0
        self._n_agents = 0
        self.print(progress=progress)

    async def external_agent_status_raise_error_callback(self) ->bool:
        return False

class BuwAgent(Agent):

    async def run(self, max_steps: int = 100, wr:BuwWriter|None=None) -> AgentHistoryList:
        logger.setLevel(LvError)
        self._writer:BuwWriter|None = wr
        if self._writer is not None:
            self.register_new_step_callback = self._writer.done_get_next_action
            self.register_done_callback = self._writer.done_agent
            #self.register_external_agent_status_raise_error_callback = self.external_agent_status_raise_error_callback
        if self._writer:
            await self._writer.start_agent(self.task)
        ret = await super().run(max_steps)
        return ret

    def _log_agent_run(self) -> None:
        super()._log_agent_run()

    async def _run_planner(self) ->str|None:
        if self._writer:
            await self._writer.start_plannner(self.state.n_steps)
        plan = await super()._run_planner()
        if self._writer:
            await self._writer.done_plannner(plan)
        return plan

    async def get_next_action(self, input_messages: list[BaseMessage]) -> AgentOutput:
        if self._writer:
            await self._writer.start_get_next_action(self.state.n_steps)
        response = await super().get_next_action(input_messages)
        return response

    async def log_completion(self) -> None:
        await super().log_completion()