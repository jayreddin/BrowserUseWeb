from dataclasses import dataclass
from typing import Type

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

    prev_action_evaluation: str
    important_contents: str
    completed_contents: str
    thought: str
    summary: str
    

class CustomAgentOutput(BaseModel):
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
			'AgentOutput',
			__base__=CustomAgentOutput,
			action=(
				list[custom_actions],
				Field(..., description='List of actions to execute', json_schema_extra={'min_items': 1}),
			),
			__module__=CustomAgentOutput.__module__,
		)
		model_.__doc__ = 'AgentOutput model with custom actions'
		return model_
