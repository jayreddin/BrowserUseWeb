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
from logging import Logger,getLogger
from dotenv import load_dotenv

logger:Logger = getLogger(__name__)

class BuwAgent(Agent):

    def __init__(self, *, task,
                 llm:BaseChatModel,page_extraction_llm:BaseChatModel|None=None,planner_llm:BaseChatModel|None=None,planner_interval:int=1,
                 browser,browser_context=None,
                 controller,
                 use_vision:bool=False,
                 max_failures: int = 3,
		         retry_delay: int = 10,
                 system_prompt_class: Type[SystemPrompt] = SystemPrompt,
                 max_input_tokens: int = 128000,
		         validate_output: bool = False,
		         message_context: Optional[str] = None,
                 writer:Callable[[str],None]|None=None,generate_gif:bool|str=False, save_conversation_path:str|None=None,
                 sensitive_data: dict[str,str]|None = None,
                 available_file_paths: Optional[list[str]] = None,
                 max_actions_per_step:int=10,
                 ):
        super().__init__(
            task=task,llm=llm,
            browser=browser,browser_context=browser_context, controller=controller,
            use_vision=use_vision, use_vision_for_planner=use_vision,
            save_conversation_path=save_conversation_path,
            max_failures=max_failures, retry_delay=retry_delay,
            system_prompt_class=system_prompt_class,
            max_input_tokens=max_input_tokens,
            validate_output=validate_output,
            message_context=message_context,
            generate_gif=generate_gif,
            sensitive_data=sensitive_data,
            available_file_paths=available_file_paths,
            max_actions_per_step=max_actions_per_step,
            page_extraction_llm=page_extraction_llm, planner_llm=planner_llm, planner_interval=planner_interval,
        )
        self._writer:Callable[[str],None]|None = writer

    def print(self,msg):
        if self._writer is None:
            print(msg)
        else:
            self._writer(msg)

    async def step(self, step_info: AgentStepInfo|None = None) -> None:
        self.print(f"----------------")
        self.print(f"STEP-{self.n_steps}")
        await super().step(step_info)

    def _log_response(self, response: AgentOutput) -> None:
        super()._log_response(response)
        self.print(f'Eval: {response.current_state.evaluation_previous_goal}')
        self.print(f'Memory: {response.current_state.memory}')
        self.print(f'Next goal: {response.current_state.next_goal}')
        for i, action in enumerate(response.action):
            self.print(f'Action {i + 1}/{len(response.action)}: {action.model_dump_json(exclude_unset=True)}')
