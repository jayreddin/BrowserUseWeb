import os
from langchain_openai import ChatOpenAI
import browser_use.controller.service
from browser_use import Agent, SystemPrompt, Controller,Browser, BrowserConfig
from browser_use.browser.context import BrowserContext
from browser_use.browser.views import BrowserState, BrowserStateHistory
from browser_use.agent.views import ActionResult, AgentOutput, AgentHistoryList, AgentStepInfo
import asyncio
from typing import Callable
from pydantic import BaseModel

os.environ["ANONYMIZED_TELEMETRY"] = "false"

wcnt = Controller()

class XAgent(Agent):

    def __init__(self, *, task,llm,browser,controller,use_vision:bool=False,writer:Callable[[str],None]|None=None):
        super().__init__(task=task,llm=llm, browser=browser, controller=controller, use_vision=use_vision)
        self._writer:Callable[[str],None]|None = writer

    def print(self,msg):
        if self._writer is None:
            print(msg)
        else:
            self._writer(msg)

    async def step(self, step_info: AgentStepInfo|None = None) -> None:
        self.print(f"----------------\nSTEP-{self.n_steps}")
        await super().step(step_info)

    def _log_response(self, response: AgentOutput) -> None:
        super()._log_response(response)
        self.print(f'Eval: {response.current_state.evaluation_previous_goal}')
        self.print(f'Memory: {response.current_state.memory}')
        self.print(f'Next goal: {response.current_state.next_goal}')
        for i, action in enumerate(response.action):
            self.print(f'Action {i + 1}/{len(response.action)}: {action.model_dump_json(exclude_unset=True)}')

class BwTask:

    def __init__(self,cdp_port:int, writer:Callable[[str],None]|None=None):
        self._writer:Callable[[str],None]|None = writer
        self.cdp_port:int = cdp_port
        self._browser:Browser = Browser( BrowserConfig(
            cdp_url=f"http://localhost:{cdp_port}"
            #chrome_instance_path="./start_chrome.sh",
            #extra_chromium_args=[str(self.display_number)],
        ) )
        self._agent:XAgent|None = None

    async def start(self,task:str):

        #br_context = await self.get_browser_context()

        self._agent = XAgent(
            task=task,
            llm=ChatOpenAI(model="gpt-4o-mini"),
            use_vision=False,
            controller=wcnt,
            browser=self._browser,
            writer=self._writer
        )
        result = await self._agent.run()
        print(result)
    
    async def stop(self):
        try:
            pass
        except:
            pass

async def main():
    task="キャトルアイサイエンス株式会社の会社概要をしらべて"
    #task="192.168.1.200にmaeda/maeda0501でログインして、通常モードに切り替えて、会議室予約に、「1/30 テストですよ 参加者前田」を追加する。"
    #task="Amazonで、格安の2.5inch HDDを探して製品URLをリストアップしてください。"
    session = BwTask(9222)
    await session.start(task)
    await session.stop()

if __name__ == "__main__":
    asyncio.run(main())

