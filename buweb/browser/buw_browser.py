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
from logging import Logger,getLogger
from dotenv import load_dotenv

logger:Logger = getLogger(__name__)


class BwDomService(DomService):

    async def _build_dom_tree(self, highlight_elements: bool, focus_element: int, viewport_expansion: int) -> DOMElementNode:
        t0 = time.time()
        try:
            #return await super()._build_dom_tree(highlight_elements, focus_element, viewport_expansion)
            return await self._custom_build_dom_tree(highlight_elements, focus_element, viewport_expansion)
        finally:
            t9 = time.time()
            logger.info(f"_build_dom_tree Time: {t9-t0:.3f}(Sec)")

    async def _custom_build_dom_tree(self, highlight_elements: bool, focus_element: int, viewport_expansion: int) -> DOMElementNode:
        #js_code = resources.read_text('browser_use.dom', 'buildDomTree.js')
        jsfile = 'buildDomTreeCustom.js'
        js_code_path = os.path.join('static',jsfile)
        with open( js_code_path, 'r', encoding='utf-8') as file:
            js_code = file.read()

        args = {
            'doHighlightElements': highlight_elements,
            'focusHighlightIndex': focus_element,
            'viewportExpansion': viewport_expansion,
        }
        t0 = time.time()
        json_str:str = await self.page.evaluate(js_code, args)  # This is quite big, so be careful
        eval_page = json.loads(json_str)
        t9 = time.time()
        logger.info(f"{js_code_path} time: {t9-t0:.3f}(Sec)")
        html_to_dict = self._parse_node(eval_page)

        if html_to_dict is None or not isinstance(html_to_dict, DOMElementNode):
            raise ValueError('Failed to parse HTML to dictionary')

        return html_to_dict

class BwBrowserContext(BrowserContext):

    def __init__(self, browser: 'Browser', config: BrowserContextConfig = BrowserContextConfig(), ):
        super().__init__(browser,config)

    async def _update_state(self, focus_element: int = -1) -> BrowserState:
        t0 = time.time()
        try:
            return await self._custom_update_state(focus_element)
        finally:
            t9 = time.time()
            logger.info(f"_custom_update_state Time: {t9-t0:.3f}(Sec)")

    async def _custom_update_state(self, focus_element: int = -1) -> BrowserState:
        """Update and return state."""
        session = await self.get_session()

        # Check if current page is still valid, if not switch to another available page
        try:
            page = await self.get_current_page()
            # Test if page is still accessible
            await page.evaluate('1')
        except Exception as e:
            logger.debug(f'Current page is no longer accessible: {str(e)}')
            # Get all available pages
            pages = session.context.pages
            if pages:
                session.current_page = pages[-1]
                page = session.current_page
                logger.debug(f'Switched to page: {await page.title()}')
            else:
                raise BrowserError('Browser closed: no valid pages available')

        try:
            await self.remove_highlights()
            dom_service = BwDomService(page)
            content = await dom_service.get_clickable_elements(
                focus_element=focus_element,
                viewport_expansion=self.config.viewport_expansion,
                highlight_elements=self.config.highlight_elements,
            )

            screenshot_b64 = await self.take_screenshot()
            pixels_above, pixels_below = await self.get_scroll_info(page)

            self.current_state = BrowserState(
                element_tree=content.element_tree,
                selector_map=content.selector_map,
                url=page.url,
                title=await page.title(),
                tabs=await self.get_tabs_info(),
                screenshot=screenshot_b64,
                pixels_above=pixels_above,
                pixels_below=pixels_below,
            )

            return self.current_state
        except Exception as e:
            logger.error(f'Failed to update state: {str(e)}')
            # Return last known good state if available
            if hasattr(self, 'current_state'):
                return self.current_state
            raise
