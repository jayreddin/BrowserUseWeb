import sys, os
sys.path.append('.')
import re,json
from importlib.resources import files
import importlib.resources as resources
from pydantic import BaseModel, Field

from buweb.Research.agent.custom_views import CustomAgentBrain, CustomAgentOutput, create_current_state_format

class User(BaseModel):
    name: str = Field(..., min_length=3, max_length=50, description="ユーザーの名前")
    age: int = Field(..., ge=18, le=100, description="年齢（18〜100）")
    
# インスタンス作成
user = User(name="Taro", age=25)
schema = user.model_json_schema()
for field,props in schema["properties"].items():
    print(f"{field}: {props['description']}")



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

if __name__ == "__main__":
    main()
