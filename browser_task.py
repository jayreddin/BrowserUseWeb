import os
from datetime import datetime
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
from langchain.chains import LLMChain
from langchain_core.messages import BaseMessage
import browser_use.controller.service
from browser_use import Agent, SystemPrompt, Controller,Browser, BrowserConfig
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.browser.views import BrowserState, BrowserStateHistory
from browser_use.agent.views import ActionResult, AgentOutput, AgentHistoryList, AgentStepInfo
import asyncio
from typing import Callable
from pydantic import BaseModel
from logging import Logger,getLogger
logger:Logger = getLogger(__name__)

os.environ["ANONYMIZED_TELEMETRY"] = "false"

class XAgent(Agent):

    def __init__(self, *, task,llm,page_extraction_llm,browser,controller,use_vision:bool=False,writer:Callable[[str],None]|None=None,generate_gif:bool|str=False, save_conversation_path:str|None=None):
        super().__init__(
            task=task,llm=llm, page_extraction_llm=page_extraction_llm,browser=browser, controller=controller, use_vision=use_vision,
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
        bconf:BrowserContextConfig = BrowserContextConfig(
            maximum_wait_page_load_time=1.0,
            viewport_expansion=0,
            browser_window_size={'width':1024,'height':1024},
        )
        if isinstance(cdp_port,int) and cdp_port>0:
            config = BrowserConfig(
                cdp_url=f"http://127.0.0.1:{cdp_port}"
            )
        elif isinstance(chrome_instance_path,str) and os.path.exists(chrome_instance_path):
            config = BrowserConfig(
                chrome_instance_path=chrome_instance_path,
                #extra_chromium_args=[str(self.display_number)],
            )
        else:
            raise ValueError("")

        self._browser:Browser = Browser( config )
        self._agent:XAgent|None = None

    def logPrint(self,msg):
        if self._writer is not None:
            self._writer(msg)
        else:
            logger.info(msg)

    async def start(self,task:str):

        now = datetime.now()
        now_datetime = now.strftime("%A, %Y-%m-%d %H:%M")
        pre_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
        pre_prompt = [
            "現在時刻:{now_datetime}",
            "ブラウザを使って以下のタスクを実行する前に、どのような情報をブラウザで収集すべきか、実行プランを考えて、目的、目標、手順、ゴールを出力して。",
            "---与えられたタスク---",
            "```",
            task,
            "```",
        ]
        pre_result:BaseMessage = await pre_llm.ainvoke( "\n".join(pre_prompt))
        plan:str|None = None
        if isinstance(pre_result.content,str):
            plan = pre_result.content
            self.logPrint(plan)

        web_task = f"# 現在時刻: {now_datetime}\n\n# 与えられたタスク:\n{task}"
        if plan is not None:
            web_task += f"\n\n実行プラン:\n{plan}"
        web_task += f"\n\n# 作業手順\n与えられたタスクと設定したゴールを満たしたか考えながら実行プランにそって実行して下さい。必要に応じて前の作業にもどったりプランを修正することも可能です。"

        #---------------------------------
        #br_context = await self.get_browser_context()
        wcnt = Controller()
        main_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
        small_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
        self._agent = XAgent(
            task=web_task,
            llm=main_llm, page_extraction_llm=small_llm,
            use_vision=False,
            controller=wcnt,
            browser=self._browser,
            writer=self._writer
        )
        result: AgentHistoryList = await self._agent.run()
        final_str = result.final_result()

        #---------------------------------
        report_task = f"# 現在時刻: {now_datetime}\n\n# 与えられたタスク:\n{task}"
        if plan is not None:
            report_task += f"\n\n# 実行プラン:\n{plan}"
        report_task += f"\n\n# 実行結果\n{final_str}\n\n# 上記の結果を日本語でレポートしてください。"
        post_result:BaseMessage = await pre_llm.ainvoke( report_task )
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
    task="キャトルアイサイエンス株式会社の会社概要をしらべて"
    #task="192.168.1.200にmaeda/maeda0501でログインして、通常モードに切り替えて、会議室予約に、「1/30 テストですよ 参加者前田」を追加する。"
    #task="Amazonで、格安の2.5inch HDDを探して製品URLをリストアップしてください。"
    session = BwTask(cdp_port=9222)
    await session.start(task)
    await session.stop()

if __name__ == "__main__":
    asyncio.run(main())

