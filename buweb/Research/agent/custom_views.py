from dataclasses import dataclass, field, fields
from typing import Type, Any
import re,json

from browser_use.browser.views import TabInfo, BrowserState
from browser_use.agent.views import AgentStepInfo, AgentBrain, AgentOutput
from browser_use.controller.registry.views import ActionModel
from pydantic import BaseModel, ConfigDict, Field, create_model
from browser_use.dom.views import DOMState, DOMElementNode, SelectorMap

# BrowserStateの内容に変更はないけれど、プロンプトのためにfieldを設定する
@dataclass
class CustomBrowserState(DOMState):

    url: str = field(metadata={ "prompt":"Current URL", "description": "The webpage you're currently on"})
    title: str
    tabs: list[TabInfo] = field(metadata={ "prompt":"Available tabs", "description": "List of open browser tabs"})
    screenshot: str|None = None
    pixels_above: int = 0
    pixels_below: int = 0
    browser_errors: list[str] = field(default_factory=list)
    element_tree:DOMElementNode = field(metadata={
        "prompt":"Interactive Elements",
        "description": (
            "List in the format:",
            "index[:]<element_type>element_text</element_type>",
            " - index: Numeric identifier for interaction",
            " - element_type: HTML element type (button, input, etc.)",
            " - element_text: Visible text or element description",
            "",
            "Example:",
            "33[:]<button>Submit Form</button>",
            "_[:] Non-interactive text",
            "",
            "Notes:",
            "- Only elements with numeric indexes are interactive",
            "- _[:] elements provide context but cannot be interacted with",
            #
            "[index]<type>text</type>",
            "- index: Numeric identifier for interaction",
            "- type: HTML element type (button, input, etc.)",
            "- text: Element description",
            "Example:",
            "[33]<button>Submit Form</button>",
            "",
            "- Only elements with numeric indexes in [] are interactive",
            "- elements without [] provide only context",
        )})

# StepInfoの内容にプロパティを追加する
@dataclass
class CustomAgentStepInfo(AgentStepInfo):
    step_number: int
    max_steps: int
    task: str = field(metadata={ "prompt":"Task", "description": "user\'s instructions you need to complete."})
    add_infos: str = field(metadata={ "prompt":"Hints(Optional)", "description": "Some hints to help you complete the user\'s instructions."})
    memory: str = field(metadata={ "prompt":"Memory", "description": "Important contents are recorded during historical operations for use in subsequent operations."})
    task_progress: str = field(metadata={ "prompt":"Task Progress", "description": "Up to the current page, the content you have completed can be understood as the progress of the task."})
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
        model_.__doc__ = 'AgentOutput model with custom actions'
        return model_

def _scan_field_names( data_class:Type, name_list:list[str]=[]):
    if hasattr(data_class,"__dataclass_fields__"):
        for field in data_class.__dataclass_fields__.values():
            if field.name in name_list:
                name_list.remove(field.name)
            name_list.append(field.name)
    if hasattr(data_class,"__bases__"):
        for base in data_class.__bases__:
            _scan_field_names(base, name_list)
    return name_list

def create_browser_state_format(dataclass_classes:Type|tuple[Type,...], indent:str="", prefix:str="", result:list[str]=[]):
    class_list = dataclass_classes if isinstance(dataclass_classes,tuple|list) else (dataclass_classes,)
    no:int = 1
    for cls in class_list:
        # 継承の深さを調べる
        name_list = _scan_field_names(cls)
        # ダンプ
        next_indent = indent + "   "
        is_dataclass = hasattr(cls,"__dataclass_fields__")
        for field_name in name_list:
            if is_dataclass and field_name in cls.__dataclass_fields__:
                field_info = cls.__dataclass_fields__[field_name]
                title = field_info.metadata.get("prompt")
                description = field_info.metadata.get("description")
                header = f"{prefix}{no}."
                if title and description:
                    if isinstance(description,str):
                        description = [description]
                    result.append( (f"{indent}{header} {title}: {description[0]}") )
                    for desc in description[1:]:
                        result.append( (f"{next_indent}{desc}") )
                    no += 1
                create_browser_state_format(field_info.type, next_indent, header, result)
    return result

def create_browser_state_values( dataclass_classes:tuple[tuple[Type,Any],...], values:dict={}, indent:str="", prefix:str="", result:list[str]=[]):
    #obj_list:tuple[Type,Any] = dataclass_classes if isinstance(dataclass_classes,tuple|list) else (dataclass_classes,)
    no:int = 1
    for clsobj in dataclass_classes:
        cls, obj = clsobj
        # 継承の深さを調べる
        name_list = _scan_field_names(cls)
        # ダンプ
        next_indent = indent + "   "
        is_dataclass = hasattr(cls,"__dataclass_fields__")
        for field_name in name_list:
            if is_dataclass and field_name in cls.__dataclass_fields__:
                field_info = cls.__dataclass_fields__[field_name]
                value = None
                if field_name in values:
                    value = values[field_name]
                elif obj is not None:
                    value = getattr(obj,field_name)
                title = field_info.metadata.get("prompt")
                description = field_info.metadata.get("description")
                header = f"{prefix}{no}."
                if title and description:
                    result.append( (f"{indent}{header} {title}:") )
                    if value:
                        result.append( (f"{next_indent}{value}") )
                    else:
                        result.append("")
                    no += 1
                if field_name not in values:
                    create_browser_state_values( ( (field_info.type,value), ), values, next_indent, header, result)
    return result

def create_current_state_format( model_class:Type[BaseModel] ) -> str:
    """system_prompt.mdのRESPOSE_FORMATに挿入するcurrent_stateのフォーマットを作成する"""
    current_state_field = model_class.model_fields.get('current_state')
    current_state_class = current_state_field.annotation if current_state_field else None
    current_state_schema = current_state_class.model_json_schema() if current_state_class else None
    if current_state_schema:
        dump = {}
        for field,props in current_state_schema["properties"].items():
            dump[field] = props.get('description',"")
        return json.dumps(dump, ensure_ascii=False)
    else:
        raise ValueError("current_state field not found")