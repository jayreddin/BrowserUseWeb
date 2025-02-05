import os
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import SecretStr
from enum import Enum
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from langchain_core.messages import BaseMessage
from langchain_core.language_models.chat_models import BaseChatModel
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
    Gemini20FlashExp = "gemini-2.0-flash-exp"
    Gemini20FlashThinkExp = "gemini-2.0-flash-thinking-exp-01-21"

def create_model( model:str|LLM,temperature:float=0.0):
    model_name = model.value if isinstance(model,LLM) else str(model)
    if model_name == LLM.Gpt4oMini.value or model_name == LLM.Gpt4o.value or model_name == LLM.O3Mini.value:
        openai_api_key = os.getenv('OPENAI_API_KEY')
        if not openai_api_key:
            raise ValueError('OPENAI_API_KEY is not set')
        return ChatOpenAI(model=model_name, temperature=temperature)
    elif model_name == LLM.Gemini20FlashExp.value or model_name == LLM.Gemini20FlashThinkExp.value:
        gemini_api_key = os.getenv('GOOGLE_API_KEY')
        if not gemini_api_key:
            raise ValueError('GEMINI_API_KEY is not set')
        return ChatGoogleGenerativeAI(model=model_name)# ,api_key=SecretStr(gemini_api_key))        
    else:
        raise ValueError(f"Invalid model name: {model_name}")

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
                 llm,page_extraction_llm=None,planner_llm=None,
                 browser,browser_context=None,
                 controller,
                 use_vision:bool=False,
                 writer:Callable[[str],None]|None=None,generate_gif:bool|str=False, save_conversation_path:str|None=None):
        super().__init__(
            task=task,llm=llm, page_extraction_llm=page_extraction_llm, planner_llm=planner_llm,
            browser=browser,browser_context=browser_context, controller=controller, use_vision=use_vision,
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

    def __init__(self,*, chrome_instance_path:str|None=None, cdp_port:int|None, trace_path:str|None=None, writer:Callable[[str],None]|None=None):
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
        elif isinstance(chrome_instance_path,str) and os.path.exists(chrome_instance_path):
            bw_config = BrowserConfig(
                chrome_instance_path=chrome_instance_path,
                #extra_chromium_args=[str(self.display_number)],
            )
        else:
            raise ValueError("")

        self._browser:Browser = Browser( bw_config )
        self._browser_context:BrowserContext = BrowserContext( self._browser, bw_context_config)
        self._agent:XAgent|None = None

    def logPrint(self,msg):
        if self._writer is not None:
            self._writer(msg)
        else:
            logger.info(msg)

    async def start(self,task:str,expand:bool):

        now = datetime.now()
        now_datetime = now.strftime("%A, %Y-%m-%d %H:%M")

        self.logPrint("")
        self.logPrint("-------------------------------------")
        self.logPrint(f"実行開始: {now_datetime}")
        self.logPrint("-------------------------------------")

        plan:str|None = None
        if expand:
            pre_llm = create_model( LLM.Gemini20FlashExp ) # ChatOpenAI(model="gpt-4o", temperature=0.0)
            pre_prompt = [
                "現在時刻:{now_datetime}",
                "ブラウザを使って以下のタスクを実行するために、目的、ブラウザで収集すべき情報、手順、ゴールを考えて、簡潔で短い文章で実行プランを出力して。",
                "---与えられたタスク---",
                "```",
                task,
                "```",
            ]
            pre_result:BaseMessage = await pre_llm.ainvoke( "\n".join(pre_prompt))
            if isinstance(pre_result.content,str):
                plan = pre_result.content
                self.logPrint(plan)

        web_task = f"# 現在時刻: {now_datetime}\n\n# 与えられたタスク:\n{task}"
        if plan is not None:
            web_task += f"\n\n実行プラン:\n{plan}"
        web_task += f"\n\n# 作業手順\n与えられたタスクと設定したゴールを満たしたか考えながら実行プランにそって実行して下さい。必要に応じて前の作業にもどったりプランを修正することも可能です。"

        #---------------------------------
        #br_context = await self.get_browser_context()
        wcnt = BwController()
        main_llm = create_model(LLM.Gemini20FlashExp) # ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
        small_llm = create_model(LLM.Gemini20FlashExp) # ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
        self._agent = XAgent(
            task=web_task,
            llm=main_llm, page_extraction_llm=small_llm,
            use_vision=False,
            controller=wcnt,
            browser=self._browser,
            browser_context=self._browser_context,
            writer=self._writer
        )
        result: AgentHistoryList = await self._agent.run()
        final_str = result.final_result()

        #---------------------------------
        post_llm = create_model(LLM.Gemini20FlashExp) # ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
        report_task = f"# 現在時刻: {now_datetime}\n\n# 与えられたタスク:\n{task}"
        if plan is not None:
            report_task += f"\n\n# 実行プラン:\n{plan}"
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
    if os.path.exists('config.env'):
        load_dotenv('config.env')
    task="キャトルアイサイエンス株式会社の会社概要をしらべて"
    #task="192.168.1.200にmaeda/maeda0501でログインして、通常モードに切り替えて、会議室予約に、「1/30 テストですよ 参加者前田」を追加する。"
    #task="Amazonで、格安の2.5inch HDDを探して製品URLをリストアップしてください。"
    session = BwTask(cdp_port=9222)
    await session.start(task,True)
    await session.stop()

if __name__ == "__main__":
    asyncio.run(main())

