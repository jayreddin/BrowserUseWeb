import sys, os
sys.path.append('.')
import re,json
from importlib.resources import files
import importlib.resources as resources
from pydantic import BaseModel, Field
from dataclasses import dataclass, field, fields
from browser_use.dom.views import DOMState, DOMElementNode, SelectorMap
from buweb.Research.agent.custom_views import CustomBrowserState, CustomAgentStepInfo, CustomAgentBrain, CustomAgentOutput, create_browser_state_format, create_browser_state_values, create_current_state_format

# Pydantic
class TabInfo(BaseModel):
	"""Represents information about a browser tab"""

	page_id: int
	url: str
	title: str



class User(BaseModel):
    name: str = Field(..., min_length=3, max_length=50, description="ユーザーの名前")
    age: int = Field(..., ge=18, le=100, description="年齢（18〜100）")

def main3():
    # インスタンス作成
    user = User(name="Taro", age=25)
    schema = user.model_json_schema()
    for field,props in schema["properties"].items():
        print(f"{field}: {props['description']}")

def main2():
    prompt:str = '\n'.join( create_browser_state_format(CustomBrowserState) )
    print(prompt)

def main():

    prompt_template = resources.read_text('buweb.Research.agent', 'system_prompt.md')
    prompt_template = "aaa {current_state_format} {{ccc}}"
    # prompt_templateから、正規表現で {} で囲まれた変数を取り出す
    pattern = r'(?<!{){([^{}]+)}(?!})'
    variables = re.findall(pattern, prompt_template)
    print("テンプレート内の変数:")
    for v in variables:
        print(v)
    #　ダンプする
    current_state_fmt = create_current_state_format(CustomAgentOutput)
    print("------------------------------------")
    print(current_state_fmt)
    print("------------------------------------")
    kwargs = {
        'current_state_format': current_state_fmt
    }
    x = prompt_template.format( **kwargs )
    print("------------------------------------")
    print(x)

def main4():

    input_fmt1 = '\n'.join( create_browser_state_format( (CustomAgentStepInfo,CustomBrowserState) ) )

    print(f"{input_fmt1}")
    print("-------------------------------------------------")
    step_info:CustomAgentStepInfo = CustomAgentStepInfo(
        step_number=1, max_steps=10,
        task="click",
        add_infos="button",
        memory="submit",
        task_progress="ボタンをクリックして送信する"
    )
    state:CustomBrowserState = CustomBrowserState(
        url="https://www.google.com",
        title="Google",
        tabs=[],
        screenshot="",
        pixels_above=0,
        pixels_below=0,
        element_tree=DOMElementNode(is_visible=True, parent=None, tag_name="", xpath="", attributes={}, children=[]),
        selector_map=SelectorMap(),
        browser_errors=[]
    )
    values = {
        'element_tree': 'abcdefg',
    }
    input_value = '\n'.join( create_browser_state_values( ( (CustomAgentStepInfo,step_info), (CustomBrowserState,state)), values ) )
    print(f"{input_value}")

if __name__ == "__main__":
    main4()
