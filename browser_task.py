import os
os.environ["ANONYMIZED_TELEMETRY"] = "false"
from datetime import datetime
import time
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
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
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.browser.views import BrowserState, BrowserStateHistory
from browser_use.agent.views import ActionResult, AgentOutput, AgentHistoryList, AgentStepInfo
#from browser_use.controller.views import ScrollAction
import asyncio
from typing import Callable, Optional, Dict,Literal
from pydantic import BaseModel
from logging import Logger,getLogger
from dotenv import load_dotenv
logger:Logger = getLogger(__name__)

os.environ["ANONYMIZED_TELEMETRY"] = "false"

class LLM(Enum):
    Gpt4o = "gpt-4o"
    Gpt4oMini = "gpt-4o-mini"
    O3Mini = "o3-mini"
    Gemini20Flash = "gemini-2.0-flash-exp"
    Gemini20FlashThink = "gemini-2.0-flash-thinking-exp-01-21"
    Gemini20Pro = "gemini-2.0-pro-exp-02-05"

    @staticmethod
    def get_lite_model(llm:"LLM") -> "LLM":
        if llm==LLM.Gpt4o or llm==LLM.Gpt4oMini or llm==LLM.O3Mini:
            return LLM.Gpt4oMini
        if llm==LLM.Gemini20Flash or llm==LLM.Gemini20Pro or llm==LLM.Gemini20FlashThink:
            return LLM.Gemini20Flash

    @staticmethod
    def get_llm(name:"str|LLM|None") -> "LLM|None":
        if isinstance(name,LLM) or name is None:
            return name
        for llm in LLM:
            if name==llm.name or name==llm.value:
                return llm
        return None

def create_model( model:str|LLM,temperature:float=0.0,cache:BaseCache|None=None) -> BaseChatModel:
    llm = LLM.get_llm(model)
    if llm == LLM.Gpt4oMini or llm == LLM.Gpt4o or llm == LLM.O3Mini:
        openai_api_key = os.getenv('OPENAI_API_KEY')
        if not openai_api_key:
            raise ValueError('OPENAI_API_KEY is not set')
        return ChatOpenAI(model=llm.value, temperature=temperature, cache=cache)
    elif llm == LLM.Gemini20Flash or llm == LLM.Gemini20FlashThink or llm==LLM.Gemini20Pro:
        kw = None
        if os.getenv('GEMINI_API_KEY') is not None:
            kw = SecretStr(os.getenv('GEMINI_API_KEY')) # type: ignore
        elif os.getenv('GOOGLE_API_KEY') is not None:
            kw = SecretStr(os.getenv('GOOGLE_API_KEY')) # type: ignore
        if kw is None:
            raise ValueError('GEMINI_API_KEY or GOOGLE_API_KEY is not set')
        if llm==LLM.Gemini20FlashThink:
            return ChatGoogleGenerativeAI(model=llm.value, cache=cache, api_key=kw)
        else:
            return ChatGoogleGenerativeAI(model=llm.value,temperature=temperature, cache=cache, api_key=kw)
    else:
        raise ValueError(f"Invalid model name: {model}")

class ScrAction(BaseModel):
	amount: Literal['half','full'] = 'full'

class BwController(Controller):
    def __init__(self):
        super().__init__()
        self._browser:Browser|None = None
        self._register_custom_actions()

    def _register_custom_actions(self):
        """Register all default browser actions"""
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

    async def act(
		self,
		action: ActionModel,
		browser_context: BrowserContext,
		page_extraction_llm: Optional[BaseChatModel] = None,
		sensitive_data: Optional[Dict[str, str]] = None,
	) -> ActionResult:
            return await super().act(action,browser_context,page_extraction_llm,sensitive_data)

class XAgent(Agent):

    def __init__(self, *, task,
                 llm:BaseChatModel,page_extraction_llm:BaseChatModel|None=None,planner_llm:BaseChatModel|None=None,planner_interval:int=1,
                 browser,browser_context=None,
                 controller,
                 use_vision:bool=False,
                 writer:Callable[[str],None]|None=None,generate_gif:bool|str=False, save_conversation_path:str|None=None):
        super().__init__(
            task=task,llm=llm, page_extraction_llm=page_extraction_llm, planner_llm=planner_llm, planner_interval=planner_interval,
            browser=browser,browser_context=browser_context, controller=controller,
            use_vision=use_vision, use_vision_for_planner=use_vision,
            generate_gif=generate_gif, save_conversation_path=save_conversation_path,
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

class BwTask:

    def __init__(self,*, dir:str,
                llm_cache:BaseCache|None=None, llm:LLM=LLM.Gpt4oMini, plan_llm:LLM|None=None,
                chrome_instance_path:str|None=None, cdp_port:int|None=None, trace_path:str|None=None,
                writer:Callable[[str],None]|None=None):
        self._work_dir:str = dir
        if llm_cache is None:
            llm_cache = SQLiteCache( os.path.join(dir,'langchain_cache.db') )
        self._operator_llm:LLM = llm
        self._plan_llm:LLM|None = plan_llm
        self._llm_cache:BaseCache = llm_cache
        self._writer:Callable[[str],None]|None = writer
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
        self._agent:XAgent|None = None

    def logPrint(self,msg):
        if self._writer is not None:
            self._writer(msg)
        else:
            logger.info(msg)

    async def start(self,task:str):

        now = datetime.now()
        now_datetime = now.strftime("%A, %Y-%m-%d %H:%M")

        x_extractor = LLM.get_lite_model(self._operator_llm)
        x_planner:str = self._plan_llm.value if self._plan_llm is not None else "None"
        self.logPrint("")
        self.logPrint("-------------------------------------")
        self.logPrint(f"実行開始: {now_datetime}")
        self.logPrint("-------------------------------------")
        self.logPrint(f"operator:{self._operator_llm.value}")
        self.logPrint(f"extractor:{x_extractor.value}")
        self.logPrint(f"planner:{x_planner}")
        llm_cache:BaseCache = self._llm_cache
        operator_llm:BaseChatModel = create_model(self._operator_llm, cache=llm_cache)
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
                self.logPrint(plan_text)

        web_task = f"# 現在時刻: {now_datetime}\n\n# 与えられたタスク:\n{task}"
        if plan_text is not None:
            web_task += f"\n\n実行プラン:\n{plan_text}"
        web_task += f"\n\n# 作業手順\n与えられたタスクと設定したゴールを満たしたか考えながら実行プランにそって実行して下さい。必要に応じて前の作業にもどったりプランを修正することも可能です。"

        #---------------------------------
        #br_context = await self.get_browser_context()
        wcnt = BwController()

        final_str:str|None = None
        try:
            self._agent = XAgent(
                task=web_task,
                llm=operator_llm, page_extraction_llm=extraction_llm, planner_llm=planner_llm, planner_interval=1,
                use_vision=False,
                controller=wcnt,
                browser=self._browser,
                browser_context=self._browser_context,
                writer=self._writer
            )
            result: AgentHistoryList = await self._agent.run()
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
            report_task += f"\n\n# 実行結果\n{final_str}\n\n# 上記の結果を日本語でレポートしてください。"
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

async def main():
    # from session import SessionStore, BwSession
    if os.path.exists('config.env'):
        load_dotenv('config.env')
    task="キャトルアイサイエンス株式会社の会社概要をしらべて"
    #task="192.168.1.200にmaeda/maeda0501でログインして、通常モードに切り替えて、会議室予約に、「1/30 テストですよ 参加者前田」を追加する。"
    #task="Amazonで、格安の2.5inch HDDを探して製品URLをリストアップしてください。"
    workdir = os.path.abspath("tmp/testrun")
    os.makedirs(workdir,exist_ok=True)
    btask = BwTask(dir=workdir,llm=LLM.Gemini20Flash)
    await btask.start(task)
    await btask.stop()
    print("done")

async def test_hilight():
    """ハイライトが遅いのかを確認するテスト"""
    workdir = os.path.abspath("tmp/testrun")
    os.makedirs(workdir,exist_ok=True)
    btask = BwTask(dir=workdir,llm=LLM.Gemini20Flash)

    browser_context = btask._browser_context
    page = await browser_context.get_current_page()
    await page.goto("https://www.amazon.co.jp/")
    await page.wait_for_load_state()
    # ---
    session = await browser_context.get_session()
    cached_selector_map = session.cached_state.selector_map
    cached_path_hashes = set(e.hash.branch_path_hash for e in cached_selector_map.values())
    print(cached_path_hashes)
    # ---
    new_state = await browser_context.get_state()
    new_path_hashes = set(e.hash.branch_path_hash for e in new_state.selector_map.values())
    print(new_path_hashes)

    print("done")

if __name__ == "__main__":
    asyncio.run(main())

