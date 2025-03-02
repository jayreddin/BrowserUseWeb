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
from browser_use.dom.views import DOMElementNode, SelectorMap
from playwright.async_api import Page
import asyncio
from typing import Callable, Optional, Dict,Literal, Type
from pydantic import BaseModel
from logging import Logger,getLogger,ERROR as LvError
from dotenv import load_dotenv

logger:Logger = getLogger(__name__)

class BuwWriter:
    def __init__(self,writer:Callable[[str],None]|None=None):
        self._writer:Callable[[str],None]|None = writer
        self._n_steps:int=0

    def print(self,msg):
        if self._writer is None:
            print(f"##AgemtPrint {msg}")
        else:
            self._writer(msg)

    async def start_agent(self,n_steps:int):
        self._n_steps = n_steps
        self.print(f"----------------")
        self.print(f"STEP-{n_steps}")

    async def start_plannner(self,n_steps:int):
        self.print(f"Planner: {self._n_steps}")

    async def done_plannner(self,plan:str|None):
        self.print(f"Planner: {plan}")

    async def get_next_action(self):
        self.print(f"Action: {self._n_steps}")

    async def new_step_callback(self, state: BrowserState, output: AgentOutput, step: int):
        self.print(f'Eval: {output.current_state.evaluation_previous_goal}')
        self.print(f'Memory: {output.current_state.memory}')
        self.print(f'Next goal: {output.current_state.next_goal}')
        # for i, action in enumerate(output.action):
        #     self.print(f'Action {i + 1}/{len(output.action)}: {action.model_dump_json(exclude_unset=True)}')

    async def action(self,action:AgentOutput):
        self.print(f"Action:{action}")

    async def done_callback(self, history: AgentHistoryList):
        self.print(f"Done:")
        pass

    async def external_agent_status_raise_error_callback(self) ->bool:
        return False

class BuwAgent(Agent):

    def print(self,msg):
        if self._writer is None:
            print(f"##AgemtPrint {msg}")
        else:
            self._writer.print(msg)

    async def run(self, max_steps: int = 100, wr:BuwWriter|None=None) -> AgentHistoryList:
        logger.setLevel(LvError)
        self._writer:BuwWriter|None = wr
        if self._writer is not None:
            self.register_new_step_callback = self._writer.new_step_callback
            self.register_done_callback = self._writer.done_callback
            #self.register_external_agent_status_raise_error_callback = self.external_agent_status_raise_error_callback
        if self._writer:
            await self._writer.start_agent(self.state.n_steps)
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
            await self._writer.get_next_action()
        response = await super().get_next_action(input_messages)
        return response

    async def log_completion(self) -> None:
        await super().log_completion()