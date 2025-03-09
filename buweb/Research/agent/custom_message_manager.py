from __future__ import annotations

import logging
from typing import List, Optional, Type, Dict

from browser_use.agent.message_manager.service import MessageManager, MessageManagerSettings
from browser_use.agent.message_manager.views import MessageHistory
from browser_use.agent.prompts import SystemPrompt 
from browser_use.agent.views import ActionResult, AgentStepInfo, ActionModel
from browser_use.agent.views import ActionResult, AgentOutput, AgentStepInfo, MessageManagerState
from browser_use.browser.views import BrowserState
from langchain_core.language_models import BaseChatModel
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
	AIMessage,
	BaseMessage,
	HumanMessage,
    ToolMessage
)
from langchain_openai import ChatOpenAI
# from ..utils.llm import DeepSeekR1ChatOpenAI
from .custom_prompts import CustomAgentMessagePrompt
from .custom_views import CustomAgentStepInfo

logger = logging.getLogger(__name__)

class CustomMessageManager(MessageManager):

    def _init_messages(self) -> None:
        """Initialize the message history with system message, context, task, and other initial messages"""
        self._add_message_with_tokens(self.system_prompt)

        if self.settings.message_context:
            context_message = HumanMessage(content='Context for the task' + self.settings.message_context)
            self._add_message_with_tokens(context_message)

        # Custom: Move Task info to state_message
        #task_message = HumanMessage(
        #    content=f'Your ultimate task is: """{self.task}""". If you achieved your ultimate task, stop everything and use the done action in the next step to complete the task. If not, continue as usual.'
        #)
        #self._add_message_with_tokens(task_message)

        if self.settings.sensitive_data:
            info = f'Here are placeholders for sensitve data: {list(self.settings.sensitive_data.keys())}'
            info += 'To use them, write <secret>the placeholder name</secret>'
            info_message = HumanMessage(content=info)
            self._add_message_with_tokens(info_message)

        placeholder_message = HumanMessage(content='Example output:')
        self._add_message_with_tokens(placeholder_message)

        tool_calls = [
            {
                'name': 'CustomAgentOutput',
                'args': {
                    'current_state': {
                        'prev_action_evaluation': 'Unknown - No previous actions to evaluate.',
                        'important_contents': '',
                        'completed_contents': '',
                        'thought': 'Now Google is open. Need to type OpenAI to search.',
                        'summary': 'Type OpenAI to search.',
                    },
                    'action': [{'click_element': {'index': 0}}],
                },
                'id': str(self.state.tool_id),
                'type': 'tool_call',
            }
        ]

        example_tool_call = AIMessage(
            content='',
            tool_calls=tool_calls,
        )
        self._add_message_with_tokens(example_tool_call)
        self.add_tool_message(content='Browser started')

        placeholder_message = HumanMessage(content='[Your task history memory starts here]')
        self._add_message_with_tokens(placeholder_message)

        if self.settings.available_file_paths:
            filepaths_msg = HumanMessage(content=f'Here are file paths you can use: {self.settings.available_file_paths}')
            self._add_message_with_tokens(filepaths_msg)
       
    def add_state_message(
        self,
        state: BrowserState,
        result: Optional[List[ActionResult]] = None,
        step_info: Optional[CustomAgentStepInfo] = None,
        use_vision=True,
    ) -> None:
        """Add browser state as human message"""

        # if keep in memory, add to directly to history and add state without result
        if result:
            for r in result:
                if r.include_in_memory:
                    if r.extracted_content:
                        msg = HumanMessage(content='Action result: ' + str(r.extracted_content))
                        self._add_message_with_tokens(msg)
                    if r.error:
                        # if endswith \n, remove it
                        if r.error.endswith('\n'):
                            r.error = r.error[:-1]
                        # get only last line of error
                        last_line = r.error.split('\n')[-1]
                        msg = HumanMessage(content='Action error: ' + last_line)
                        self._add_message_with_tokens(msg)
                    result = None  # if result in history, we dont want to add it again

        # otherwise add state message and result to next message (which will not stay in memory)
        state_message = CustomAgentMessagePrompt(
            state,
            result,
            include_attributes=self.settings.include_attributes,
            step_info=step_info,
        ).get_user_message(use_vision)
        self._add_message_with_tokens(state_message)

