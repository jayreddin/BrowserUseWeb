import os
from langchain_openai import ChatOpenAI
import browser_use.controller.service
from browser_use import Agent, SystemPrompt, Controller,Browser, BrowserConfig
from browser_use.browser.context import BrowserContext
from browser_use.browser.views import BrowserState, BrowserStateHistory
from browser_use.agent.views import ActionResult, AgentOutput, AgentHistoryList, AgentStepInfo
import asyncio
from pydantic import BaseModel

os.environ["ANONYMIZED_TELEMETRY"] = "false"

wcnt = Controller()

class XAgent(Agent):
    async def step(self, step_info: AgentStepInfo|None = None) -> None:
        print(f"##[STEP] STEP-{self.n_steps}")
        await super().step(step_info)

    def _log_response(self, response: AgentOutput) -> None:
        super()._log_response(response)
        print(f'##[log_response] Eval: {response.current_state.evaluation_previous_goal}')
        print(f'[log_response] Memory: {response.current_state.memory}')
        print(f'[log_response] Next goal: {response.current_state.next_goal}')
        for i, action in enumerate(response.action):
            print(f'[log_response] Action {i + 1}/{len(response.action)}: {action.model_dump_json(exclude_unset=True)}')

class BWSession:

    def __init__(self,cdp_port:int):
        self.cdp_port:int = cdp_port
        self._browser:Browser = Browser( BrowserConfig(
            cdp_url=f"http://localhost:{cdp_port}"
            #chrome_instance_path="./start_chrome.sh",
            #extra_chromium_args=[str(self.display_number)],
        ) )
        self._agent:XAgent|None = None

    async def start(self):

        #br_context = await self.get_browser_context()
        task="キャトルアイサイエンス株式会社の会社概要をしらべて"
        #task="192.168.1.200にmaeda/maeda0501でログインして、通常モードに切り替えて、会議室予約に、「1/30 テストですよ 参加者前田」を追加する。"
        #task="Amazonで、格安の2.5inch HDDを探して製品URLをリストアップしてください。"
        self._agent = XAgent(
            task=task,
            llm=ChatOpenAI(model="gpt-4o-mini"),
            use_vision=False,
            controller=wcnt,
            browser=self._browser
        )
        result = await self._agent.run()
        print(result)
    
    async def stop_browser(self):
        try:
            pass
        except:
            pass

    async def stop(self):
        try:
            await self.stop_browser()
        except:
            pass

async def main():
    session = BWSession(9222)
    await session.start()
    await session.stop()

if __name__ == "__main__":
    asyncio.run(main())

