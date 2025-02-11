import sys,os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import asyncio
import logging
from uuid import uuid4
#from src.agent.custom_agent import CustomAgent
import json
import re
from typing import Optional, Type, List, Dict, Any, Callable
from lmnr import observe
from dataclasses import dataclass
os.environ["ANONYMIZED_TELEMETRY"] = "false"
from browser_use.agent.service import Agent
from browser_use.browser.browser import BrowserConfig, Browser
from browser_use import ActionModel, Agent, SystemPrompt, Controller,Browser, BrowserConfig
from browser_use.agent.prompts import AgentMessagePrompt
from browser_use.agent.views import ActionResult, AgentOutput, AgentHistoryList, AgentStepInfo
from browser_use.browser.context import BrowserContext, BrowserContextConfig
from browser_use.utils import time_execution_async

from langchain.schema import BaseMessage, SystemMessage, HumanMessage
from langchain_core.language_models.chat_models import BaseChatModel

from json_repair import repair_json

from buweb.agent.custom_prompts import CustomSystemPrompt, CustomAgentMessagePrompt
#from buweb.controller.custom_controller import CustomController
from buweb.model.model import LLM, create_model

logger = logging.getLogger(__name__)

@dataclass
class CustomAgentStepInfo:
    step_number: int
    max_steps: int
    task: str
    add_infos: str
    memory: str
    task_progress: str
    future_plans: str

class XAgent(Agent):
    def __init__(self, task:str, llm:BaseChatModel,
                add_infos:str, 
                browser:Browser|None=None, browser_context:BrowserContext|None=None, 
                use_vision:bool=False, 
                system_prompt_class: Type[SystemPrompt] = SystemPrompt,
                agent_prompt_class: Type[AgentMessagePrompt] = AgentMessagePrompt,
                max_actions_per_step:int = 10, 
                controller:Controller = Controller(), 
                agent_state=None
                ):
        super().__init__(
            task=task,
            llm=llm,
            browser=browser,
            browser_context=browser_context,
            controller=controller,
            use_vision=use_vision,
            #save_conversation_path=save_conversation_path,
            #max_failures=max_failures,
            #retry_delay=retry_delay,
            system_prompt_class=system_prompt_class,
            #max_input_tokens=max_input_tokens,
            #validate_output=validate_output,
            #include_attributes=include_attributes,
            #max_error_length=max_error_length,
            max_actions_per_step=max_actions_per_step,
            #tool_call_in_content=tool_call_in_content,
            #initial_actions=initial_actions,
            #register_new_step_callback=register_new_step_callback,
            #register_done_callback=register_done_callback,
            #tool_calling_method=tool_calling_method
        )
        self.add_infos:str = add_infos
        self.agent_prompt_class: Type[AgentMessagePrompt] = agent_prompt_class

    @observe(name='agent.run', ignore_output=True)
    async def run(self, max_steps: int = 100) -> AgentHistoryList:
        """Execute the task with maximum number of steps"""
        try:
            self._log_agent_run()

            # Execute initial actions if provided
            if self.initial_actions:
                result = await self.controller.multi_act(
                    self.initial_actions,
                    self.browser_context,
                    check_for_new_elements=False,
                    page_extraction_llm=self.page_extraction_llm,
                    check_break_if_paused=lambda: self._check_if_stopped_or_paused(),
                )
                self._last_result = result

            step_info = CustomAgentStepInfo(
                task=self.task,
                add_infos=self.add_infos,
                step_number=1,
                max_steps=max_steps,
                memory="",
                task_progress="",
                future_plans=""
            )

            for step in range(max_steps):
                if self._too_many_failures():
                    break

                # Check control flags before each step
                if not await self._handle_control_flags():
                    break

                await self.step(step_info)

                if self.history.is_done():
                    if self.validate_output and step < max_steps - 1:
                        if not await self._validate_output():
                            continue

                    logger.info('✅ Task completed successfully')
                    if self.register_done_callback:
                        self.register_done_callback(self.history)
                    break
            else:
                logger.info('❌ Failed to complete task in maximum steps')

            return self.history
        finally:
            if not self.injected_browser_context:
                await self.browser_context.close()

            if not self.injected_browser and self.browser:
                await self.browser.close()

            if self.generate_gif:
                output_path: str = 'agent_history.gif'
                if isinstance(self.generate_gif, str):
                    output_path = self.generate_gif

                self.create_history_gif(output_path=output_path)

    @observe(name='agent.step', ignore_output=True, ignore_input=True)
    @time_execution_async('--step')
    async def step(self, step_info: Optional[AgentStepInfo] = None) -> None:
        """Execute one step of the task"""
        logger.info(f'📍 Step {self.n_steps}')
        state = None
        model_output = None
        result: list[ActionResult] = []

        try:
            state = await self.browser_context.get_state()

            self._check_if_stopped_or_paused()
            self.message_manager.add_state_message(state, self._last_result, step_info, self.use_vision)

            # Run planner at specified intervals if planner is configured
            if self.planner_llm and self.n_steps % self.planning_interval == 0:
                plan = await self._run_planner()
                # add plan before last state message
                self.message_manager.add_plan(plan, position=-1)

            input_messages = self.message_manager.get_messages()

            self._check_if_stopped_or_paused()

            try:
                model_output = await self.get_next_action(input_messages)

                if self.register_new_step_callback:
                    self.register_new_step_callback(state, model_output, self.n_steps)

                self._save_conversation(input_messages, model_output)
                self.message_manager._remove_last_state_message()  # we dont want the whole state in the chat history

                self._check_if_stopped_or_paused()

                self.message_manager.add_model_output(model_output)
            except Exception as e:
                # model call failed, remove last state message from history
                self.message_manager._remove_last_state_message()
                raise e

            result: list[ActionResult] = await self.controller.multi_act(
                model_output.action,
                self.browser_context,
                page_extraction_llm=self.page_extraction_llm,
                sensitive_data=self.sensitive_data,
                check_break_if_paused=lambda: self._check_if_stopped_or_paused(),
            )
            self._last_result = result

            if len(result) > 0 and result[-1].is_done:
                logger.info(f'📄 Result: {result[-1].extracted_content}')

            self.consecutive_failures = 0

        except InterruptedError:
            logger.debug('Agent paused')
            self._last_result = [
                ActionResult(
                    error='The agent was paused - now continuing actions might need to be repeated', include_in_memory=True
                )
            ]
            return
        except Exception as e:
            result = await self._handle_step_error(e)
            self._last_result = result

        finally:
            if not result:
                return

            if state:
                self._make_history_item(model_output, state, result)

async def deep_research(task, llm:BaseChatModel, agent_state=None, max_query_num:int=3, max_search_iterations:int=10, **kwargs):
    #max_search_iterations = kwargs.get("max_search_iterations", 10)  # Limit search iterations to prevent infinite loop
    use_vision = kwargs.get("use_vision", False)
    max_steps = kwargs.get("max_steps", 10)
    task_id = str(uuid4())
    save_dir = kwargs.get("save_dir", os.path.join(f"./tmp/deep_research/{task_id}"))
    logger.info(f"Save Deep Research at: {save_dir}")
    os.makedirs(save_dir, exist_ok=True)

    browser:Browser|None = None
    browser_context:BrowserContext|None = None
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
    search_messages:list[BaseMessage] = [SystemMessage(content=search_system_prompt)]

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
    record_messages:list[BaseMessage] = [SystemMessage(content=record_system_prompt)]

    search_iteration = 0

    history_query = []
    history_infos = []
    try:
        while search_iteration < max_search_iterations:
            search_iteration += 1
            logger.info(f"Start {search_iteration}th Search...")
            history_query_ = json.dumps(history_query, indent=4)
            history_infos_ = json.dumps(history_infos, indent=4)
            query_prompt = f"This is search {search_iteration} of {max_search_iterations} maximum searches allowed.\n User Instruction:{task} \n Previous Queries:\n {history_query_} \n Previous Search Results:\n {history_infos_}\n"
            search_messages.append(HumanMessage(content=query_prompt))
            ai_query_msg = llm.invoke(search_messages[:1] + search_messages[1:][-1:])
            search_messages.append(ai_query_msg)
            if hasattr(ai_query_msg, "reasoning_content"):
                logger.info("🤯 Start Search Deep Thinking: ")
                logger.info(ai_query_msg.reasoning_content) # type: ignore
                logger.info("🤯 End Search Deep Thinking")
            ai_query_contentx = str(ai_query_msg.content).replace("```json", "").replace("```", "")
            ai_query_contentx = repair_json(ai_query_contentx)
            ai_query_content = json.loads(ai_query_content)
            query_plan = ai_query_content["plan"]
            logger.info(f"Current Iteration {search_iteration} Planing:")
            logger.info(query_plan)
            query_tasks = ai_query_content["queries"]
            if not query_tasks:
                break
            else:
                query_tasks = query_tasks[:max_query_num]
                history_query.extend(query_tasks)
                logger.info("Query tasks:")
                logger.info(query_tasks)

            # 2. Perform Web Search and Auto exec
            # Parallel BU agents
            add_infos = "1. Please click on the most relevant link to get information and go deeper, instead of just staying on the search page. \n" \
                        "2. When opening a PDF file, please remember to extract the content using extract_content instead of simply opening it for the user to view.\n"
            agents:list[XAgent] = [XAgent(
                task=task,
                llm=llm,
                add_infos=add_infos,
                browser=browser,
                browser_context=browser_context,
                use_vision=use_vision,
                system_prompt_class=CustomSystemPrompt,
                agent_prompt_class=CustomAgentMessagePrompt,
                max_actions_per_step=5,
                controller=controller,
                agent_state=agent_state
            ) for task in query_tasks]
            query_results:list[AgentHistoryList] = await asyncio.gather(
                *[agent.run(max_steps=max_steps) for agent in agents])

            if agent_state and agent_state.is_stop_requested():
                # Stop
                break
            # 3. Summarize Search Result
            query_result_dir = os.path.join(save_dir, "query_results")
            os.makedirs(query_result_dir, exist_ok=True)
            for i in range(len(query_tasks)):
                query_result = query_results[i].final_result()
                if not query_result:
                    continue
                querr_save_path = os.path.join(query_result_dir, f"{search_iteration}-{i}.md")
                logger.info(f"save query: {query_tasks[i]} at {querr_save_path}")
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
                        logger.info("🤯 Start Record Deep Thinking: ")
                        logger.info(ai_record_msg.reasoning_content) # type: ignore
                        logger.info("🤯 End Record Deep Thinking")
                    record_contentx = str(ai_record_msg.content)
                    record_contentx = repair_json(record_contentx)
                    new_record_infos = json.loads(record_contentx)
                    history_infos.extend(new_record_infos)

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
            logger.info(ai_report_msg.reasoning_content) # type: ignore
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
        if browser:
            await browser.close()
        if browser_context:
            await browser_context.close()
        logger.info("Browser closed.")

async def testrun():
    llm:BaseChatModel = create_model(LLM.Gemini20Flash)
    await deep_research("リサーチ機能の開発テスト中", llm)

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv('config.env')
    asyncio.run(testrun())