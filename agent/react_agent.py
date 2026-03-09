from langchain.agents import create_agent
from model.factory import chat_model
from utils.prompt_loader import load_system_prompts
from agent.tools.agent_tools import (rag_summarize, get_weather, get_user_location, get_user_id,
                                     get_current_month, search_course, search_campus_location, 
                                     get_campus_calendar, search_club, search_scholarship, 
                                     get_academic_info, search_dormitory, contact_support)
from agent.tools.middleware import monitor_tool, log_before_model


class ReactAgent:
    def __init__(self):
        self.agent = create_agent(
            model=chat_model,
            system_prompt=load_system_prompts(),
            tools=[rag_summarize, get_weather, get_user_location, get_user_id, get_current_month,
                   search_course, search_campus_location, get_campus_calendar, search_club, 
                   search_scholarship, get_academic_info, search_dormitory, contact_support],
            middleware=[monitor_tool, log_before_model],
        )

    def execute_stream(self, query: str):
        input_dict = {
            "messages": [
                {"role": "user", "content": query},
            ]
        }

        # 校园问答助手执行查询
        for chunk in self.agent.stream(input_dict, stream_mode="values"):
            latest_message = chunk["messages"][-1]
            if latest_message.content:
                yield latest_message.content.strip() + "\n"


if __name__ == '__main__':
    agent = ReactAgent()

    for chunk in agent.execute_stream("新生需要了解哪些校园信息？"):
        print(chunk, end="", flush=True)
