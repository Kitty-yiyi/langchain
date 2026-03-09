from typing import Callable
from utils.prompt_loader import load_system_prompts, load_report_prompts
from langchain.agents import AgentState
from langchain.agents.middleware import wrap_tool_call, before_model, dynamic_prompt, ModelRequest
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command
from utils.logger_handler import logger

# wrap_tool_call装饰器用于将monitor_tool函数包装为一个工具调用的监控函数，以便在工具被调用时记录相关日志信息。
@wrap_tool_call
# monitor_tool函数是一个工具调用的监控函数，用于在工具被调用时记录相关日志信息。它接受两个参数：request和handler。
# request参数是一个ToolCallRequest对象，封装了工具调用的相关信息，如工具名称和传入参数等。handler参数是一个可调用对象，表示要执行的工具函数本身。
# 在函数内部，首先记录工具调用的名称和传入参数，然后尝试执行工具函数，并记录工具调用成功的日志信息。如果工具调用的名称是"fill_context_for_report"，还会在请求的运行时上下文中设置一个标记，表示当前是报告生成的场景。最后，函数返回工具函数的执行结果。如果工具调用过程中发生异常，会记录错误日志并重新抛出异常。
def monitor_tool(
        # 请求的数据封装
        request: ToolCallRequest,
        # 执行的函数本身
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:             # 工具执行的监控
    logger.info(f"[tool monitor]执行工具：{request.tool_call['name']}")
    logger.info(f"[tool monitor]传入参数：{request.tool_call['args']}")

    try:
        result = handler(request)
        logger.info(f"[tool monitor]工具{request.tool_call['name']}调用成功")

        if request.tool_call['name'] == "fill_context_for_report":
            request.runtime.context["report"] = True

        return result
    except Exception as e:
        logger.error(f"工具{request.tool_call['name']}调用失败，原因：{str(e)}")
        raise e

# before_model装饰器用于将log_before_model函数注册为一个模型调用前的钩子函数，以便在模型被调用之前执行相关的日志记录操作。
@before_model
# log_before_model函数是一个模型调用前的日志记录函数，用于在模型被调用之前记录相关日志信息。它接受两个参数：state和runtime。
# state参数是一个AgentState对象，包含了智能体(agent)的当前状态信息，如消息记录等。runtime参数是一个Runtime对象，记录了整个执行过程中的上下文信息。
# 在函数内部，首先记录即将调用模型的日志信息，包括当前消息记录的数量。然后，记录最后一条消息的类型和内容，以便在模型调用前了解最新的对话状态。最后，函数返回None，表示不对模型调用过程进行任何修改。
def log_before_model(
        state: AgentState,          # 整个Agent智能体中的状态记录
        runtime: Runtime,           # 记录了整个执行过程中的上下文信息
):         # 在模型执行前输出日志
    logger.info(f"[log_before_model]即将调用模型，带有{len(state['messages'])}条消息。")

    logger.debug(f"[log_before_model]{type(state['messages'][-1]).__name__} | {state['messages'][-1].content.strip()}")

    return None

# dynamic_prompt装饰器用于将report_prompt_switch函数注册为一个动态提示词切换函数，以便在生成提示词之前根据上下文信息动态切换提示词内容。
@dynamic_prompt                 # 每一次在生成提示词之前，调用此函数
def report_prompt_switch(request: ModelRequest):     # 动态切换提示词
    is_report = request.runtime.context.get("report", False)
    if is_report:               # 是报告生成场景，返回报告生成提示词内容
        return load_report_prompts()

    return load_system_prompts()
