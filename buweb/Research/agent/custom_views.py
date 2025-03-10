from dataclasses import dataclass
from typing import Type
import re,json

from browser_use.agent.views import AgentStepInfo, AgentBrain, AgentOutput
from browser_use.controller.registry.views import ActionModel
from pydantic import BaseModel, ConfigDict, Field, create_model


@dataclass
class CustomAgentStepInfo:
    step_number: int
    max_steps: int
    task: str
    add_infos: str
    memory: str
    task_progress: str
    def is_last_step(self) -> bool:
        """Check if this is the last step"""
        return self.step_number >= self.max_steps - 1

class CustomAgentBrain(BaseModel):
    """Current state of the agent"""
    prev_action_evaluation: str = Field(...,description="Success|Failed|Unknown - Analyze the current elements and the image to check if the previous goals/actions are successful like intended by the task. Ignore the action result. The website is the ground truth. Also mention if something unexpected happened like new suggestions in an input field. Shortly state why/why not. Note that the result you output must be consistent with the reasoning you output afterwards. If you consider it to be 'Failed,' you should reflect on this during your thought.")
    important_contents: str = Field(...,description="Output important contents closely related to user\'s instruction or task on the current page. If there is, please output the contents. If not, please output empty string ''.")
    completed_contents: str = Field(...,description="Update the input Task Progress. Completed contents is a general summary of the current contents that have been completed. Just summarize the contents that have been actually completed based on the current page and the history operations. Please list each completed item individually, such as: 1. Input username. 2. Input Password. 3. Click confirm button")
    thought: str = Field(...,description="Think about the requirements that have been completed in previous operations and the requirements that need to be completed in the next one operation. If the output of prev_action_evaluation is 'Failed', please reflect and output your reflection here. If you think you have entered the wrong page, consider to go back to the previous page in next action.")
    summary: str = Field(...,description="Please generate a brief natural language description for the operation in next actions based on your Thought.")

    # log_responseを動かすために、以下のプロパティが必要
    # next_goalはcreate_history_gifでも必要

    @property
    def evaluation_previous_goal(self) -> str:
        return self.prev_action_evaluation

    @property
    def memory(self) -> str:
        return self.thought

    @property
    def next_goal(self) -> str:
        return self.thought

class CustomAgentOutput(AgentOutput):
	"""Output model for agent

	@dev note: this model is extended with custom actions in AgentService. You can also use some fields that are not in this model as provided by the linter, as long as they are registered in the DynamicActions model.
	"""

	model_config = ConfigDict(arbitrary_types_allowed=True)

	current_state: CustomAgentBrain
	action: list[ActionModel] = Field(
		...,
		description='List of actions to execute',
		json_schema_extra={'min_items': 1},  # Ensure at least one action is provided
	)

	@staticmethod
	def type_with_custom_actions(custom_actions: Type[ActionModel]) -> Type['CustomAgentOutput']:
		"""Extend actions with custom actions"""
		model_ = create_model(
			'CustomAgentOutput',
			__base__=CustomAgentOutput,
			action=(
				list[custom_actions],
				Field(..., description='List of actions to execute', json_schema_extra={'min_items': 1}),
			),
			__module__=CustomAgentOutput.__module__,
		)
		model_.__doc__ = 'CustomAgentOutput model with custom actions'
		return model_

def create_current_state_format( agent_output_class:Type[BaseModel] ) -> str:
    """system_prompt.mdのRESPOSE_FORMATに挿入するcurrent_stateのフォーマットを作成する"""
    current_state_field = agent_output_class.model_fields.get('current_state')
    current_state_class = current_state_field.annotation if current_state_field else None
    current_state_schema = current_state_class.model_json_schema() if current_state_class else None
    if current_state_schema:
        dump = {}
        for field,props in current_state_schema["properties"].items():
            dump[field] = props.get('description',"")
        return json.dumps(dump, ensure_ascii=False)
    else:
        raise ValueError("current_state field not found")