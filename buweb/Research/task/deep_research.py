import pdb

from dotenv import load_dotenv

load_dotenv()
import asyncio
import sys,os
os.environ["ANONYMIZED_TELEMETRY"] = "false"
#sys.path.append(os.path.abspath('.'))
sys.path.append(os.path.abspath('.'))
#sys.path.append(os.path.abspath('./src/Research'))
import time
from datetime import datetime
from shutil import rmtree
from logging import getLogger, Logger
from pprint import pprint
from uuid import uuid4
#from src.utils import utils
import json
import re
from json_repair import repair_json

from langchain.schema import SystemMessage, HumanMessage
from langchain_core.rate_limiters import BaseRateLimiter, InMemoryRateLimiter

from browser_use.controller.service import Controller

from buweb.Research.agent.custom_agent import CustomAgent
from buweb.Research.agent.custom_prompts import CustomSystemPrompt

alogger = getLogger(__name__)

class CustomRateLimiter(BaseRateLimiter):
    def __init__(self, requests_per_minute:int, requests_per_day:int, record_file_path:str|None ):
        self.requests_per_minute = requests_per_minute
        self.requests_per_day = requests_per_day
        self.requests_in_day:int = 0
        self.requests_in_minute:list[float] = []
        dt = datetime.now().strftime("%Y-%m-%d")
        self.current_date = dt
        self.record_file_path = record_file_path
        if record_file_path and os.path.exists(record_file_path):
            with open(record_file_path, "r") as fr:
                aaa = json.load(fr)
                b = aaa.get(f'requests_in_{dt}',0.0)
                if isinstance(b,int|float):
                    self.requests_in_day = int(b)
                c = aaa.get('requests_in_minute',[])
                if isinstance(c,list):
                    self.requests_in_minute = c
    def _save(self,dt):
        if self.record_file_path:
            with open(self.record_file_path, "w") as fr:
                json.dump( {f'requests_in_{dt}': self.requests_in_day, 'requests_in_minute': self.requests_in_minute},fr)

    def _can_acquire(self) ->bool:
        dt = datetime.now().strftime("%Y-%m-%d")
        if dt != self.current_date:
            self.requests_in_day = 0
            self.current_date = dt
        if self.requests_in_day>=self.requests_per_day:
            print(f"RateLimit: requests per day {self.requests_in_day}/{self.requests_per_day}")
            return False
        now = time.time()
        while len(self.requests_in_minute)>0 and now-self.requests_in_minute[0]>60.0:
            print(f"RateLimit: RPM {len(self.requests_in_minute)}/{self.requests_per_minute}")
            self.requests_in_minute.pop(0)
        if len(self.requests_in_minute)>=self.requests_per_minute:
            return False
        self.requests_in_day += 1
        self.requests_in_minute.append(now)
        self._save(dt)
        return True

    def acquire(self, *, blocking: bool = True) -> bool:
        if blocking:
            while not self._can_acquire():
                time.sleep(1.0)
            return True
        else:
            return self._can_acquire()

    async def aacquire(self, *, blocking: bool = True) -> bool:
        if blocking:
            while not self._can_acquire():
                await asyncio.sleep(1.0)
            return True
        else:
            return self._can_acquire()

def fmtdict(msg:dict,indent:str=""):
    for k,v in msg.items():
        if isinstance(v,dict):
            yield f"{indent}{str(k)}:"
            yield from fmtdict(v,indent+"  ")
        else:
            yield f"{indent}{str(k)}: {str(v)}"
class dump:
    def __init__(self,logger:Logger|None):
        self.logger = logger

    def fmt(self, msg:str|dict):
        if isinstance(msg,dict):
            msg = "\n".join(fmtdict(msg))
        return msg

    def info(self,msg:str|dict):
        print(self.fmt(msg))

    def error(self,msg:str|dict):
        print(self.fmt(msg))

async def safe_close(item):
    try:
        await item.close() # 
    except:
        pass

logger = dump(alogger)

async def deep_research(task, llm, **kwargs):
    task_id = 'testrun' # str(uuid4())
    save_dir = kwargs.get("save_dir", os.path.join(f"./tmp/deep_research/{task_id}"))
    logger.info(f"Save Deep Research at: {save_dir}")
    if os.path.exists(save_dir):
        rmtree(save_dir,ignore_errors=True)
    os.makedirs(save_dir, exist_ok=True)

    # max qyery num per iteration
    max_query_num = kwargs.get("max_query_num", 3)

    browser = None
    browser_context = None

    controller = Controller()

    search_system_prompt = f"""
    You are a **Deep Researcher**, an AI agent specializing in in-depth information gathering and research using a web browser with **automated execution capabilities**. Your expertise lies in formulating comprehensive research plans and executing them meticulously to fulfill complex user requests. You will analyze user instructions, devise a detailed research plan, and determine the necessary search queries to gather the required information.

    **Your Task:**

    Given a user's research topic, you will:

    1. **Develop a Research Plan:** Outline the key aspects and subtopics that need to be investigated to thoroughly address the user's request. This plan should be a high-level overview of the research direction.
    2. **Generate Search Queries:** Based on your research plan, generate a list of specific search queries to be executed in a web browser. These queries should be designed to efficiently gather relevant information for each aspect of your plan.

    **Output Format:**

    Your output will be a JSON object with the following structure:

    ```json
    {{
    "plan": "A concise, high-level research plan outlining the key areas to investigate.",
      "queries": [
        "search query 1",
        "search query 2",
        //... up to a maximum of {max_query_num} search queries
      ]
    }}
    ```

    **Important:**

    *   Limit your output to a **maximum of {max_query_num}** search queries.
    *   Make the search queries to help the automated agent find the needed information. Consider what keywords are most likely to lead to useful results.
    *   If you have gathered for all the information you want and no further search queries are required, output queries with an empty list: `[]`
    *   Make sure output search queries are different from the history queries.

    **Inputs:**

    1.  **User Instruction:** The original instruction given by the user.
    2.  **Previous Queries:** History Queries.
    3.  **Previous Search Results:** Textual data gathered from prior search queries. If there are no previous search results this string will be empty.
    """
    search_messages:list[SystemMessage|HumanMessage] = [SystemMessage(content=search_system_prompt)]

    record_system_prompt = """
    You are an expert information recorder. Your role is to process user instructions, current search results, and previously recorded information to extract, summarize, and record new, useful information that helps fulfill the user's request. Your output will be a JSON formatted list, where each element represents a piece of extracted information and follows the structure: `{"url": "source_url", "title": "source_title", "summary_content": "concise_summary", "thinking": "reasoning"}`.

**Important Considerations:**

1. **Minimize Information Loss:** While concise, prioritize retaining important details and nuances from the sources. Aim for a summary that captures the essence of the information without over-simplification. **Crucially, ensure to preserve key data and figures within the `summary_content`. This is essential for later stages, such as generating tables and reports.**

2. **Avoid Redundancy:** Do not record information that is already present in the Previous Recorded Information. Check for semantic similarity, not just exact matches. However, if the same information is expressed differently in a new source and this variation adds valuable context or clarity, it should be included.

3. **Source Information:** Extract and include the source title and URL for each piece of information summarized. This is crucial for verification and context. **The Current Search Results are provided in a specific format, where each item starts with "Title:", followed by the title, then "URL Source:", followed by the URL, and finally "Markdown Content:", followed by the content. Please extract the title and URL from this structure.** If a piece of information cannot be attributed to a specific source from the provided search results, use `"url": "unknown"` and `"title": "unknown"`.

4. **Thinking and Report Structure:**  For each extracted piece of information, add a `"thinking"` key. This field should contain your assessment of how this information could be used in a report, which section it might belong to (e.g., introduction, background, analysis, conclusion, specific subtopics), and any other relevant thoughts about its significance or connection to other information.

**Output Format:**

Provide your output as a JSON formatted list. Each item in the list must adhere to the following format:

```json
[
  {
    "url": "source_url_1",
    "title": "source_title_1",
    "summary_content": "Concise summary of content. Remember to include key data and figures here.",
    "thinking": "This could be used in the introduction to set the context. It also relates to the section on the history of the topic."
  },
  // ... more entries
  {
    "url": "unknown",
    "title": "unknown",
    "summary_content": "concise_summary_of_content_without_clear_source",
    "thinking": "This might be useful background information, but I need to verify its accuracy. Could be used in the methodology section to explain how data was collected."
  }
]
```

**Inputs:**

1. **User Instruction:** The original instruction given by the user. This helps you determine what kind of information will be useful and how to structure your thinking.
2. **Previous Recorded Information:** Textual data gathered and recorded from previous searches and processing, represented as a single text string.
3. **Current Search Plan:** Research plan for current search.
4. **Current Search Query:** The current search query.
5. **Current Search Results:** Textual data gathered from the most recent search query.
    """
    record_messages:list[SystemMessage|HumanMessage] = [SystemMessage(content=record_system_prompt)]

    search_iteration = 0
    max_search_iterations = kwargs.get("max_search_iterations", 10)  # Limit search iterations to prevent infinite loop
    use_vision = kwargs.get("use_vision", False)

    history_query = []
    history_infos = []
    try:
        while search_iteration < max_search_iterations:
            search_iteration += 1
            ititle = f"Ite:{search_iteration:02d}"
            logger.info(f"{ititle} Start Search...")
            history_query_ = json.dumps(history_query, indent=4)
            history_infos_ = json.dumps(history_infos, indent=4)
            query_prompt = f"This is search {search_iteration} of {max_search_iterations} maximum searches allowed.\n User Instruction:{task} \n Previous Queries:\n {history_query_} \n Previous Search Results:\n {history_infos_}\n"
            search_messages.append(HumanMessage(content=query_prompt))
            ai_query_msg = llm.invoke(search_messages[:1] + search_messages[1:][-1:])
            search_messages.append(ai_query_msg)
            if hasattr(ai_query_msg, "reasoning_content"):
                logger.info(f"{ititle} 🤯 Start Search Deep Thinking: ")
                logger.info(ai_query_msg.reasoning_content)
                logger.info(f"{ititle} 🤯 End Search Deep Thinking")
            ai_query_contents:str = ai_query_msg.content.replace("```json", "").replace("```", "")
            ai_query_contenta = repair_json(ai_query_contents)
            ai_query_content = json.loads(ai_query_contenta) # type: ignore
            query_plan = ai_query_content["plan"]
            logger.info(f"{ititle} Current Iteration Planing:")
            logger.info(query_plan)
            query_tasks = ai_query_content["queries"]
            if not query_tasks:
                break
            else:
                query_tasks = query_tasks[:max_query_num]
                history_query.extend(query_tasks)
                logger.info(f"{ititle} Query tasks:")
                logger.info(query_tasks)

            # 2. Perform Web Search and Auto exec
            # Parallel BU agents
            agents = [CustomAgent(
                task=task,
                llm=llm,
                browser=browser,
                browser_context=browser_context,
                use_vision=use_vision,
                system_prompt_class=CustomSystemPrompt,
                max_actions_per_step=5,
                controller=controller,
            ) for task in query_tasks]

            query_result_dir = os.path.join(save_dir, "query_results")
            os.makedirs(query_result_dir, exist_ok=True)

            query_results = []
            for i in range(len(agents)):
                title = f"Query:{search_iteration:02d}-{i:03d}"
                agent = agents[i]
                logger.info(f"{title} Search...")
                res = await agent.run(max_steps=kwargs.get("max_steps", 10))
                query_results.append(res)
                query_result = res.final_result()
                if not query_result:
                    logger.info(f"{title} no final result")
                    continue
                querr_save_path = os.path.join(query_result_dir, f"{search_iteration}-{i}.md")
                logger.info(f"{title} save query: {query_tasks[i]} at {querr_save_path}")
                with open(querr_save_path, "w", encoding="utf-8") as fw:
                    fw.write(f"Query: {query_tasks[i]}\n")
                    fw.write(query_result)

                # split query result in case the content is too long
                query_results_split = query_result.split("Extracted page content:")
                for qi, query_result_ in enumerate(query_results_split):
                    if not query_result_:
                        continue
                    else:
                        # TODO: limit content lenght: 128k tokens, ~3 chars per token
                        query_result_ = query_result_[:128000 * 3]
                    history_infos_ = json.dumps(history_infos, indent=4)
                    record_prompt = f"User Instruction:{task}. \nPrevious Recorded Information:\n {history_infos_}\n Current Search Iteration: {search_iteration}\n Current Search Plan:\n{query_plan}\n Current Search Query:\n {query_tasks[i]}\n Current Search Results: {query_result_}\n "
                    record_messages.append(HumanMessage(content=record_prompt))
                    ai_record_msg = llm.invoke(record_messages[:1] + record_messages[-1:])
                    record_messages.append(ai_record_msg)
                    if hasattr(ai_record_msg, "reasoning_content"):
                        logger.info(f"{title} 🤯 Start Record Deep Thinking: ")
                        logger.info(ai_record_msg.reasoning_content)
                        logger.info(f"{title} 🤯 End Record Deep Thinking")
                    record_content = ai_record_msg.content
                    record_content = repair_json(record_content)
                    new_record_infos = json.loads(record_content)  # type: ignore
                    history_infos.extend(new_record_infos)

            # 3. Summarize Search Result

        logger.info("\nFinish Searching, Start Generating Report...")

        # 5. Report Generation in Markdown (or JSON if you prefer)
        writer_system_prompt = """
        You are a **Deep Researcher** and a professional report writer tasked with creating polished, high-quality reports that fully meet the user's needs, based on the user's instructions and the relevant information provided. You will write the report using Markdown format, ensuring it is both informative and visually appealing.

**Specific Instructions:**

*   **Structure for Impact:** The report must have a clear, logical, and impactful structure. Begin with a compelling introduction that immediately grabs the reader's attention. Develop well-structured body paragraphs that flow smoothly and logically, and conclude with a concise and memorable conclusion that summarizes key takeaways and leaves a lasting impression.
*   **Engaging and Vivid Language:** Employ precise, vivid, and descriptive language to make the report captivating and enjoyable to read. Use stylistic techniques to enhance engagement. Tailor your tone, vocabulary, and writing style to perfectly suit the subject matter and the intended audience to maximize impact and readability.
*   **Accuracy, Credibility, and Citations:** Ensure that all information presented is meticulously accurate, rigorously truthful, and robustly supported by the available data. **Cite sources exclusively using bracketed sequential numbers within the text (e.g., [1], [2], etc.). If no references are used, omit citations entirely.** These numbers must correspond to a numbered list of references at the end of the report.
*   **Publication-Ready Formatting:** Adhere strictly to Markdown formatting for excellent readability and a clean, highly professional visual appearance. Pay close attention to formatting details like headings, lists, emphasis, and spacing to optimize the visual presentation and reader experience. The report should be ready for immediate publication upon completion, requiring minimal to no further editing for style or format.
*   **Conciseness and Clarity (Unless Specified Otherwise):** When the user does not provide a specific length, prioritize concise and to-the-point writing, maximizing information density while maintaining clarity.
*   **Data-Driven Comparisons with Tables:**  **When appropriate and beneficial for enhancing clarity and impact, present data comparisons in well-structured Markdown tables. This is especially encouraged when dealing with numerical data or when a visual comparison can significantly improve the reader's understanding.**
*   **Length Adherence:** When the user specifies a length constraint, meticulously stay within reasonable bounds of that specification, ensuring the content is appropriately scaled without sacrificing quality or completeness.
*   **Comprehensive Instruction Following:** Pay meticulous attention to all details and nuances provided in the user instructions. Strive to fulfill every aspect of the user's request with the highest degree of accuracy and attention to detail, creating a report that not only meets but exceeds expectations for quality and professionalism.
*   **Reference List Formatting:** The reference list at the end must be formatted as follows:  
    `[1] Title (URL, if available)`
    **Each reference must be separated by a blank line to ensure proper spacing.** For example:

    ```
    [1] Title 1 (URL1, if available)

    [2] Title 2 (URL2, if available)
    ```
    **Furthermore, ensure that the reference list is free of duplicates. Each unique source should be listed only once, regardless of how many times it is cited in the text.**
*   **ABSOLUTE FINAL OUTPUT RESTRICTION:**  **Your output must contain ONLY the finished, publication-ready Markdown report. Do not include ANY extraneous text, phrases, preambles, meta-commentary, or markdown code indicators (e.g., "```markdown```"). The report should begin directly with the title and introductory paragraph, and end directly after the conclusion and the reference list (if applicable).**  **Your response will be deemed a failure if this instruction is not followed precisely.**
        
**Inputs:**

1. **User Instruction:** The original instruction given by the user. This helps you determine what kind of information will be useful and how to structure your thinking.
2. **Search Information:** Information gathered from the search queries.
        """

        history_infos_ = json.dumps(history_infos, indent=4)
        record_json_path = os.path.join(save_dir, "record_infos.json")
        logger.info(f"save All recorded information at {record_json_path}")
        with open(record_json_path, "w") as fw:
            json.dump(history_infos, fw, indent=4)
        report_prompt = f"User Instruction:{task} \n Search Information:\n {history_infos_}"
        report_messages = [SystemMessage(content=writer_system_prompt),
                           HumanMessage(content=report_prompt)]  # New context for report generation
        ai_report_msg = llm.invoke(report_messages)
        if hasattr(ai_report_msg, "reasoning_content"):
            logger.info("🤯 Start Report Deep Thinking: ")
            logger.info(ai_report_msg.reasoning_content)
            logger.info("🤯 End Report Deep Thinking")
        report_content = ai_report_msg.content
        # Remove ```markdown or ``` at the *very beginning* and ``` at the *very end*, with optional whitespace
        report_content = re.sub(r"^```\s*markdown\s*|^\s*```|```\s*$", "", report_content, flags=re.MULTILINE)
        report_content = report_content.strip()
        report_file_path = os.path.join(save_dir, "final_report.md")
        with open(report_file_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        logger.info(f"Save Report at: {report_file_path}")
        return report_content, report_file_path

    except Exception as e:
        logger.error(f"Deep research Error: {e}")
        return "", None
    finally:
        await safe_close(browser)
        await safe_close(browser_context)
        logger.info("Browser closed.")

from langchain_google_genai import ChatGoogleGenerativeAI
from google.api_core.exceptions import ResourceExhausted as GoogleResourceExhausted
from openai import RateLimitError as OpenaiRateLimitError
class CustomChatGoogleGenerativeAI(ChatGoogleGenerativeAI):

    def invoke(self,input):
        i=0
        while True:
            i+=1
            try:
                return super().invoke(input)
            except GoogleResourceExhausted as ex1:
                if i>=30:
                    raise ex1
                if i==1:
                    print(f"{ex1}")
                time.sleep(10.0)


async def test_run():
    os.environ['GOOGLE_API_KEY']='AIzaSyDjRXeuvtlj_aTYuv2jI0KxwHf5BBnzQpQ'
    limitter = CustomRateLimiter( requests_per_minute=10, requests_per_day=1500, record_file_path='tmp/limit.json')
    llm = CustomChatGoogleGenerativeAI(  model="gemini-2.0-flash-exp")
    task = "調査の動作テストをしてください。ブラウザで何かを検索して、動作テスト結果をレポートして。"
    task = "write a report about browser-use"
    report = await deep_research(task,llm)
    print("------------------------")
    print(report)

if __name__ == "__main__":
    asyncio.run(test_run())