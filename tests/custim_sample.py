import os
import time
import asyncio
import json
from logging import getLogger
from importlib.resources import files

from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.language_models.chat_models import BaseChatModel

from browser_use import Agent, Browser
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.browser.views import BrowserError, BrowserState
from browser_use.dom.service import DomService
from browser_use.dom.views import DOMElementNode

from dotenv import load_dotenv


logger = getLogger(__name__)

CUSTOM:bool = True
#---
# custom JS code
#---
orig_js_code_path:str = str(files('browser_use.dom').joinpath('buildDomTree.js'))
with open( orig_js_code_path, 'r', encoding='utf-8') as file:
    js_code = file.read()
if CUSTOM:
    before = '''return buildDomTree(document.body);'''
    after = '''return JSON.stringify(buildDomTree(document.body));'''
    if before in js_code:
        js_code = js_code.replace(before,after)
    else:
        raise ValueError("Custom JS code not found in buildDomTree.js")                

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

    async def _build_dom_tree(self, highlight_elements: bool, focus_element: int, viewport_expansion: int) -> DOMElementNode:
		# js_code = resources.read_text('browser_use.dom', 'buildDomTree.js')

        args = {
            'doHighlightElements': highlight_elements,
            'focusHighlightIndex': focus_element,
            'viewportExpansion': viewport_expansion,
        }
        t0 = time.time()
        if CUSTOM:
            json_str:str = await self.page.evaluate(js_code, args)  # This is quite big, so be careful
            eval_page = json.loads(json_str)
        else:
            eval_page = await self.page.evaluate(js_code, args)
        t9 = time.time()
        logger.info(f"buildDomTree.js time: {t9-t0:.3f}(Sec)")
        html_to_dict = self._parse_node(eval_page)

        if html_to_dict is None or not isinstance(html_to_dict, DOMElementNode):
            raise ValueError('Failed to parse HTML to dictionary')

        return html_to_dict

class CustomBrowserContext(BrowserContext):

    def __init__(self, browser: 'Browser', config: BrowserContextConfig = BrowserContextConfig(), ):
        super().__init__(browser,config)

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
                session.current_page = pages[-1]
                page = session.current_page
                logger.debug(f'Switched to page: {await page.title()}')
            else:
                raise BrowserError('Browser closed: no valid pages available')

        try:
            await self.remove_highlights()
            dom_service = CustomDomService(page)
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
    browser_context = CustomBrowserContext(browser)

    agent = Agent(
        task="Go to Reddit, search for 'browser-use', click on the first post and return the first comment.",
        llm=create_llm(),
        browser_context=browser_context,
    )
    result = await agent.run()
    print(result)

asyncio.run(main())