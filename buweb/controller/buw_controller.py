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
import pyperclip
from logging import Logger,getLogger
from dotenv import load_dotenv

logger:Logger = getLogger(__name__)

class ScrAction(BaseModel):
	amount: Literal['half','full'] = 'full'

class UserInput(BaseModel):
    question: str
    secret: bool

class UserInputResult(BaseModel):
    qid: int
    question: str
    secret: bool
    anser: str

class BwController(Controller):
    def __init__(self,exclude_actions: list[str] = [],output_model: Optional[Type[BaseModel]] = None):
        super().__init__(exclude_actions=exclude_actions,output_model=output_model)
        self._register_custom_actions()

    def _register_custom_actions(self):
        """Register all default browser actions"""

        # import from browser-use-web-ui
        @self.registry.action("Copy text to clipboard")
        def copy_to_clipboard(text: str):
            pyperclip.copy(text)
            return ActionResult(extracted_content=text)

        # import from browser-use-web-ui
        @self.registry.action("Paste text from clipboard")
        async def paste_from_clipboard(browser: BrowserContext):
            text = pyperclip.paste()
            # send text to browser
            page = await browser.get_current_page()
            await page.keyboard.type(text)

            return ActionResult(extracted_content=text)

        # customize scroll action
        @self.registry.action(
			"Scroll down half a page with 'half' or a full page with 'full'.",
			param_model=ScrAction,
		)
        async def scroll_down(params: ScrAction, browser: BrowserContext):
            page = await browser.get_current_page()
            scr_height:int = await page.evaluate('document.documentElement.scrollHeight')
            content_height: int = await page.evaluate('window.innerHeight')
            before_pos:int = await page.evaluate('window.scrollY')
            max_height:int = scr_height - content_height
            rate = 0.5 if params.amount == 'half' else 0.9
            after_pos:int = before_pos
            target_pos = min( max_height, before_pos+int(content_height*rate))
            cnt:int = 0
            while cnt<10 and after_pos != target_pos:
                cnt += 1
                await page.evaluate(f'window.scrollBy(0, {target_pos-after_pos});')
                await page.wait_for_timeout(200)
                after_pos = await page.evaluate('window.scrollY')
            msg = f'🔍  Scrolled down the {params.amount} page. Window.scrollY changed from {before_pos} to {after_pos}.'
            logger.info(msg)
            return ActionResult(
                extracted_content=msg,
                include_in_memory=True,
            )

        # customize scroll action
        @self.registry.action(
			"Scroll up half a page with 'half' or a full page with 'full'.",
            param_model=ScrAction,
        )
        async def scroll_up(params: ScrAction, browser: BrowserContext):
            page = await browser.get_current_page()
            page = await browser.get_current_page()
            scr_height:int = await page.evaluate('document.documentElement.scrollHeight')
            content_height: int = await page.evaluate('window.innerHeight')
            before_pos:int = await page.evaluate('window.scrollY')
            rate = 0.5 if params.amount == 'half' else 0.9
            after_pos:int = before_pos
            target_pos = max( 0, before_pos-int(content_height*rate))
            cnt:int = 0
            while cnt<10 and after_pos != target_pos:
                cnt += 1
                await page.evaluate(f'window.scrollBy(0, {target_pos-after_pos});')
                await page.wait_for_timeout(200)
                after_pos = await page.evaluate('window.scrollY')
            msg = f'🔍  Scrolled up the {params.amount} page. Window.scrollY changed from {before_pos} to {after_pos}.'
            logger.info(msg)
            return ActionResult(
                extracted_content=msg,
                include_in_memory=True,
            )
        # @self.registry.action(
		# 	'Extract page content to retrieve specific information from the page, e.g. all company names, a specifc description, all information about, links with companies in structured format or simply links',
		# )
        # async def extract_content(goal: str, browser: BrowserContext, page_extraction_llm: BaseChatModel):
        #     t0 = time.time()
        #     page = await browser.get_current_page()
        #     t1 = time.time()
        #     import markdownify
        #     t2 = time.time()
        #     content = markdownify.markdownify(await page.content())
        #     t3 = time.time()
        #     prompt = 'Your task is to extract the content of the page. You will be given a page and a goal and you should extract all relevant information around this goal from the page. If the goal is vague, summarize the page. Respond in json format. Extraction goal: {goal}, Page: {page}'
        #     template = PromptTemplate(input_variables=['goal', 'page'], template=prompt)
        #     try:
        #         output = page_extraction_llm.invoke(template.format(goal=goal, page=content))
        #         t4 = time.time()
        #         print(f"### TIME get:{t1-t0}, import:{t2-t1}, markdownify:{t3-t2}, extraction:{t4-t3}")
        #         msg = f'📄  Extracted from page\n: {output.content}\n'
        #         logger.info(msg)
        #         return ActionResult(extracted_content=msg, include_in_memory=True)
        #     except Exception as e:
        #         logger.debug(f'Error extracting content: {e}')
        #         msg = f'📄  Extracted from page\n: {content}\n'
        #         logger.info(msg)
        #         return ActionResult(extracted_content=msg)

        # @self.action('Ask user for information',param_model=UserInput)
        # def ask_human(params: UserInput, browser: BrowserContext):
        #     print("Ask human")
        #     user_input = input(f'\n{question}\nInput: ')
        #     # ユーザーの入力をメモリに保存
        #     return ActionResult(extracted_content=user_input, include_in_memory=True)

    # async def act(
	# 	self,
	# 	action: ActionModel,
	# 	browser_context: BrowserContext,
	# 	page_extraction_llm: Optional[BaseChatModel] = None,
	# 	sensitive_data: Optional[Dict[str, str]] = None,
	# 	available_file_paths: Optional[list[str]] = None,
	# ) -> ActionResult:
    #         return await super().act(action,browser_context,page_extraction_llm,sensitive_data,available_file_paths)
