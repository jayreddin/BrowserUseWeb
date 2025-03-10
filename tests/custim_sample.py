import os
import time
import asyncio
import json
import re
import logging
from logging import getLogger
from importlib.resources import files
from playwright.async_api import Page

from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.language_models.chat_models import BaseChatModel

from browser_use import Agent, Browser
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.browser.views import BrowserError, BrowserState
from browser_use.dom.service import DomService
from browser_use.dom.views import DOMElementNode,SelectorMap

from dotenv import load_dotenv

logger = getLogger(__name__)

def text_diff(text1: str, text2: str) -> str:
    lines1 = text1.splitlines()
    lines2 = text2.splitlines()
    if len(lines1) != len(lines2):
        return f"Line count mismatch: {len(lines1)} vs {len(lines2)}"
    marks = [False] * len(lines1)
    width = 0
    for i, (line1, line2) in enumerate(zip(lines1, lines2)):
        if line1 != line2:
            for j in range(max(0, i-3), min(len(lines1), i+3)):
                width = max(width, len(lines1[j]))
                width = max(width, len(lines2[j]))
                marks[j] = True
    diff_lines = []
    for i, (line1, line2) in enumerate(zip(lines1, lines2)):
        if marks[i]:
            x = "|   |" if line1==line2 else "| ! |"
            diff_lines.append(f"{i}: {line1:<{width}} {x} {line2}")
    return '\n'.join(diff_lines)

def create_llm() ->BaseChatModel:
    load_dotenv('config.env')
    if not os.environ.get("GOOGLE_API_KEY"):
        if os.environ.get("GEMINI_API_KEY"):
            os.environ["GOOGLE_API_KEY"] = os.environ.get("GEMINI_API_KEY") # type: ignore
    if os.environ.get("GOOGLE_API_KEY"):
        llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp")
    elif os.environ.get("OPENAI_API_KEY"):
        llm = ChatOpenAI(model="gpt-4o-mini")
    else:
        raise Exception("Please set either OPENAI_API_KEY or GOOGLE_API_KEY in the config.env file.")
    return llm

class CustomDomService(DomService):
    def __init__(self, page: 'Page', custom:bool = False):
        super().__init__(page)
        # customized JS code
        self.js_code2 = re.sub(
            r'(return) (debugMode \?\s*{ rootId, map: DOM_HASH_MAP, perfMetrics: PERF_METRICS } :\s*{ rootId, map: DOM_HASH_MAP })',
            r'\1 JSON.stringify( \2 )',
            self.js_code
        )
        if self.js_code == self.js_code2:
            raise ValueError('Failed to modify the JS code')
        print( text_diff(self.js_code, self.js_code2) )
        self.custom:bool = custom

    # Override
    async def _build_dom_tree(
        self,
        highlight_elements: bool,
        focus_element: int,
        viewport_expansion: int,
    ) -> tuple[DOMElementNode, SelectorMap]:
        if await self.page.evaluate('1+1') != 2:
            raise ValueError('The page cannot evaluate javascript code properly')

        # NOTE: We execute JS code in the browser to extract important DOM information.
        #       The returned hash map contains information about the DOM tree and the
        #       relationship between the DOM elements.
        debug_mode = logger.getEffectiveLevel() == logging.DEBUG
        args = {
            'doHighlightElements': highlight_elements,
            'focusHighlightIndex': focus_element,
            'viewportExpansion': viewport_expansion,
            'debugMode': debug_mode,
        }

        t0 = time.time()
        if self.custom:
            method='custom'
            try:
                json_str = await self.page.evaluate(self.js_code2, args)
                eval_page = json.loads(json_str)
            except Exception as e:
                logger.error('Error evaluating JavaScript: %s', e)
                raise
        else:
            method='original'
            try:
                eval_page = await self.page.evaluate(self.js_code, args)
            except Exception as e:
                logger.error('Error evaluating JavaScript: %s', e)
                raise
        t9 = time.time()
        logger.info(f"buildDomTree.js time: {method} {t9-t0:.3f}(Sec)")

        # Only log performance metrics in debug mode
        if debug_mode and 'perfMetrics' in eval_page:
            logger.debug('DOM Tree Building Performance Metrics:\n%s', json.dumps(eval_page['perfMetrics'], indent=2))

        return await self._construct_dom_tree(eval_page)

class CustomBrowserContext(BrowserContext):

    def __init__(self, browser: 'Browser', config: BrowserContextConfig = BrowserContextConfig(), custom:bool = False):
        super().__init__(browser,config)
        self.custom:bool = custom

    async def _update_state(self, focus_element: int = -1) -> BrowserState:
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
                self.state.target_id = None
                page = await self._get_current_page(session)
                logger.debug(f'Switched to page: {await page.title()}')
            else:
                raise BrowserError('Browser closed: no valid pages available')

        try:
            await self.remove_highlights()
            dom_service = CustomDomService(page,self.custom)
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

async def main():

    browser = Browser()
    custom = True
    browser_context = CustomBrowserContext(browser, custom=custom)

    agent = Agent(
        task="Go to Reddit, search for 'browser-use', click on the first post and return the first comment.",
        llm=create_llm(),
        browser_context=browser_context,
    )
    result = await agent.run()
    print(result)

asyncio.run(main())