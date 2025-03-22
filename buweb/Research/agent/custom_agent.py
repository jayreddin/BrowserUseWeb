import json
import logging
import pdb
import traceback
from typing import Awaitable,Optional, Type, List, Dict, Any, Callable, TypeVar
from PIL import Image, ImageDraw, ImageFont
import os
import base64
import io
import platform
from browser_use.agent.prompts import SystemPrompt, AgentMessagePrompt
from browser_use.agent.service import Agent
from browser_use.agent.views import (
    ActionResult,
    ActionModel,
    AgentHistoryList,
    AgentOutput,
    AgentHistory,
    AgentStepInfo,
    AgentState,
    ToolCallingMethod,
    StepMetadata
)
from browser_use.agent.message_manager.service import MessageManager, MessageManagerSettings
from browser_use.browser.browser import Browser
from browser_use.browser.context import BrowserContext
from browser_use.browser.views import BrowserState, BrowserStateHistory
from browser_use.controller.service import Controller
from browser_use.telemetry.views import (
    AgentEndTelemetryEvent,
    AgentRunTelemetryEvent,
    AgentStepTelemetryEvent,
)
from browser_use.utils import time_execution_async
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage
)
from browser_use.agent.prompts import PlannerPrompt

from json_repair import repair_json
#from src.utils.agent_state import AgentState

from .custom_message_manager import CustomMessageManager
from .custom_views import CustomAgentOutput, CustomAgentStepInfo

from buweb.agent.buw_agent import BuwWriter
from .gif import create_history_gif

logger = logging.getLogger(__name__)

Context = TypeVar('Context')

class CustomAgent(Agent):
    def __init__(
		self,
		task: str,
		llm: BaseChatModel,
        add_infos: str = "",
		# Optional parameters
		browser: Browser | None = None,
		browser_context: BrowserContext | None = None,
		controller: Controller[Context] = Controller(),
		# Initial agent run parameters
		sensitive_data: Optional[Dict[str, str]] = None,
		initial_actions: Optional[List[Dict[str, Dict[str, Any]]]] = None,
		# Cloud Callbacks
		register_new_step_callback: Callable[['BrowserState', 'AgentOutput', int], Awaitable[None]] | None = None,
		register_done_callback: Callable[['AgentHistoryList'], Awaitable[None]] | None = None,
		register_external_agent_status_raise_error_callback: Callable[[], Awaitable[bool]] | None = None,
		# Agent settings
		use_vision: bool = True,
		use_vision_for_planner: bool = False,
		save_conversation_path: Optional[str] = None,
		save_conversation_path_encoding: Optional[str] = 'utf-8',
		max_failures: int = 3,
		retry_delay: int = 10,
		system_prompt_class: Type[SystemPrompt] = SystemPrompt,
		max_input_tokens: int = 128000,
		validate_output: bool = False,
		message_context: Optional[str] = None,
		generate_gif: bool | str = False,
		available_file_paths: Optional[list[str]] = None,
		include_attributes: list[str] = [
			'title',
			'type',
			'name',
			'role',
			'aria-label',
			'placeholder',
			'value',
			'alt',
			'aria-expanded',
			'data-date-format',
		],
		max_actions_per_step: int = 10,
		tool_calling_method: Optional[ToolCallingMethod] = 'auto',
		page_extraction_llm: Optional[BaseChatModel] = None,
		planner_llm: Optional[BaseChatModel] = None,
		planner_interval: int = 1,  # Run planner every N steps
		# Inject state
		injected_agent_state: Optional[AgentState] = None,
		#
		context: Context | None = None,
        # Custom
        writer:BuwWriter|None=None
    ):
        super().__init__(
            task=task,
            llm=llm,
            # Optional parameters
            browser=browser,
            browser_context=browser_context,
            controller=controller,
            # Initial agent run parameters
            sensitive_data=sensitive_data,
            initial_actions=initial_actions,
            # Cloud Callbacks
            register_new_step_callback=register_new_step_callback,
            register_done_callback=register_done_callback,
            register_external_agent_status_raise_error_callback=register_external_agent_status_raise_error_callback,
            # Agent settings
            use_vision=use_vision,
            use_vision_for_planner=use_vision_for_planner,
            save_conversation_path=save_conversation_path,
            save_conversation_path_encoding=save_conversation_path_encoding,
            max_failures=max_failures,
            retry_delay=retry_delay,
            system_prompt_class=system_prompt_class,
            max_input_tokens=max_input_tokens,
            validate_output=validate_output,
            message_context=message_context,
            generate_gif=generate_gif,
            available_file_paths=available_file_paths,
            include_attributes=include_attributes,
            max_actions_per_step=max_actions_per_step,
            tool_calling_method=tool_calling_method,
            page_extraction_llm=page_extraction_llm,
            planner_llm=planner_llm,
            planner_interval=planner_interval,
            # Inject state
            injected_agent_state=injected_agent_state,
            #
            context=context,
        )
        self.add_infos = add_infos
        self._writer:BuwWriter|None = writer
		# Initialize message manager with state
        self._message_manager = CustomMessageManager(
            task=task,
            system_message=self.settings.system_prompt_class(
                self.available_actions,
                max_actions_per_step=self.settings.max_actions_per_step,
            ).get_system_message(),
            settings=MessageManagerSettings(
                max_input_tokens=self.settings.max_input_tokens,
                include_attributes=self.settings.include_attributes,
                message_context=self.settings.message_context,
                sensitive_data=sensitive_data,
                available_file_paths=self.settings.available_file_paths,
            ),
            state=self.state.message_manager_state,
        )

    def print(self,msg):
        if self._writer is None:
            print(msg)
        else:
            self._writer.print(msg=msg)

    def logTrans(self,title,msg):
        if self._writer is not None:
            txt = self._writer.trans(msg)
            self._writer.print(msg=f"{title} {txt}")
        else:
            logger.info(f"{title}: {msg}")

    def _setup_action_models(self) -> None:
        """Setup dynamic action models from controller's registry"""
        self.ActionModel = self.controller.registry.create_action_model()
        # Create output model with the dynamic actions
        self.AgentOutput = CustomAgentOutput.type_with_custom_actions(self.ActionModel)
        # used to force the done action when max_steps is reached
        self.DoneActionModel = self.controller.registry.create_action_model(include_actions=['done'])
        self.DoneAgentOutput = CustomAgentOutput.type_with_custom_actions(self.DoneActionModel)

    def _log_response(self, response: CustomAgentOutput) -> None:
        """Log the model's response"""
        if 'Success' in response.current_state.prev_action_evaluation:
            emoji = '✅'
        elif 'Failed' in response.current_state.prev_action_evaluation:
            emoji = '❌'
        else:
            emoji = '🤷'

        logger.info(f'{emoji} Eval: {response.current_state.prev_action_evaluation}')
        logger.info(f'🧠 New Memory: {response.current_state.important_contents}')
        logger.info(f'⏳ Task Progress: {response.current_state.task_progress}')
        logger.info(f'🤔 Thought: {response.current_state.thought}')
        logger.info(f'🎯 Summary: {response.current_state.summary}')
        for i, action in enumerate(response.action):
            logger.info(
                f'🛠️  Action {i + 1}/{len(response.action)}: {action.model_dump_json(exclude_unset=True)}'
            )
        # self.print(f'{emoji} Eval: {response.current_state.prev_action_evaluation}')
        # self.print(f'New Memory: {response.current_state.important_contents}')
        self.print(f'Task Progress: {response.current_state.task_progress}')
        # self.print(f'Thought: {response.current_state.thought}')
        self.print(f'Summary: {response.current_state.summary}')


    def _make_history_item(
        self,
        model_output: AgentOutput | None,
        state: BrowserState,
        result: list[ActionResult],
        metadata: Optional[StepMetadata] = None,
    ) -> None:
        """Create and store history item"""

        if model_output:
            interacted_elements = AgentHistory.get_interacted_element(model_output, state.selector_map)
        else:
            interacted_elements = [None]

        state_history = BrowserStateHistory(
            url=state.url,
            title=state.title,
            tabs=state.tabs,
            interacted_element=interacted_elements,
            screenshot=state.screenshot,
        )

        history_item = AgentHistory(model_output=model_output, result=result, state=state_history, metadata=metadata)

        self.state.history.history.append(history_item)

    def update_step_info( self, model_output: CustomAgentOutput, step_info: CustomAgentStepInfo ):
        """
        update step info
        """
        step_info.step_number += 1
        important_contents = model_output.current_state.important_contents
        if (
                important_contents
                and "None" not in important_contents
                and important_contents not in step_info.memory
        ):
            step_info.memory += important_contents + "\n"

        completed_contents = model_output.current_state.task_progress
        if completed_contents and "None" not in completed_contents:
            step_info.task_progress = completed_contents
        future_plans = model_output.current_state.future_plans
        if future_plans and "None" not in future_plans:
            step_info.future_plans = future_plans
    
    async def step(self, step_info: AgentStepInfo ) ->None:
        if self.custom_step_info is None:
            self.custom_step_info = CustomAgentStepInfo(
                step_number=1,
                max_steps=step_info.max_steps,
                task=self.task,
                add_infos=self.add_infos,
                memory="",
                task_progress="",
                future_plans="",
            )
        self.custom_step_info.step_number = step_info.step_number
        self.custom_step_info.max_steps = step_info.max_steps
        await super().step(self.custom_step_info)

    async def get_next_action(self, input_messages: list[BaseMessage]) -> AgentOutput:
        if self._writer:
            await self._writer.start_get_next_action(self.state.n_steps)
        parsed = await super().get_next_action(input_messages)
        self._log_response(parsed)
        if self.custom_step_info is not None:
            self.update_step_info(parsed, self.custom_step_info)
        return parsed

    async def run(self, max_steps: int = 100, wr:BuwWriter|None=None) -> AgentHistoryList:
        self._writer = wr
        if self._writer is not None:
            self.register_new_step_callback = self._writer.done_get_next_action
        self.custom_step_info = None
        try:
            return await super().run(max_steps)
        finally:
            self.custom_step_info = None

    async def multi_act( self, actions: list[ActionModel], check_for_new_elements: bool = True ) -> list[ActionResult]:
        try:
            return await super().multi_act(actions, check_for_new_elements)
        except Exception as e:
            print("".join(traceback.format_exception(type(e), e, e.__traceback__)))
            raise e

    async def action(self,action:ActionModel|ActionResult):
        if isinstance(action,ActionModel):
            await self.start_action(action)
        elif isinstance(action,ActionResult):
            await self.done_action(action)

    async def _handle_step_error(self, error: Exception) -> list[ActionResult]:
        print("".join(traceback.format_exception(type(error), error, error.__traceback__)))
        return await super()._handle_step_error(error)