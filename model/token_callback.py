import uuid
from typing import Dict, Any, Optional
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from utils.token_counter import token_counter
from utils.logger_handler import logger

class TokenCountingCallbackHandler(BaseCallbackHandler):
    """LangChain的token计数回调处理器"""

    name = "token_counting_callback"

    def __init__(self, model_name: str = ""):
        super().__init__()
        self.model_name = model_name
        self.session_id = str(uuid.uuid4())
        self.current_prompt = ""
        self.current_response = ""

    def on_llm_start(self, serialized: Dict[str, Any], prompts: list, **kwargs: Any) -> None:
        """LLM调用开始时触发"""
        if prompts:
            self.current_prompt = prompts[0][:1000]  # 存储前1000个字符

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """LLM调用结束时触发 - 核心token统计逻辑"""
        try:
            # 从response中提取token信息
            if response.llm_output:
                # ChatTongyi返回的token信息格式
                usage = response.llm_output.get("usage", {})

                input_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)

                # 如果都没有，尝试从其他地方获取
                if input_tokens == 0 and output_tokens == 0:
                    # 尝试从generations中估算
                    if response.generations and response.generations[0]:
                        generation = response.generations[0][0]
                        # 粗略估算：中文大约1.5个字符算1个token
                        output_text = generation.text if hasattr(generation, 'text') else str(generation)
                        estimated_output_tokens = len(output_text) // 2  # 粗略估算
                        output_tokens = estimated_output_tokens

                        # 估算输入token（基于prompt长度）
                        if hasattr(self, 'current_prompt') and self.current_prompt:
                            estimated_input_tokens = len(self.current_prompt) // 2
                            input_tokens = estimated_input_tokens

                # 提取响应文本
                if response.generations and response.generations[0]:
                    self.current_response = response.generations[0][0].text[:500]

                # 记录token使用
                token_counter.record_tokens(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    model_name=self.model_name,
                    prompt=self.current_prompt,
                    response=self.current_response,
                    session_id=self.session_id,
                    metadata={
                        "handler": "llm_end",
                        "model": self.model_name,
                    }
                )

                logger.info(
                    f"[TokenCallback] Model={self.model_name} | "
                    f"Input={input_tokens} | Output={output_tokens} | "
                    f"Total={input_tokens + output_tokens}"
                )
        except Exception as e:
            logger.error(f"[TokenCallback] 处理token时出错: {str(e)}")

    def on_llm_error(self, error: Exception, **kwargs: Any) -> None:
        """LLM调用出错时触发"""
        logger.warning(f"[TokenCallback] LLM调用出错: {str(error)}")

class StreamingTokenCallbackHandler(BaseCallbackHandler):
    """流式输出的token计数回调处理器"""

    name = "streaming_token_callback"

    def __init__(self, model_name: str = ""):
        super().__init__()
        self.model_name = model_name
        self.session_id = str(uuid.uuid4())
        self.accumulated_response = ""

    def on_llm_new_token(self, token: str, **kwargs: Any) -> None:
        """每个新token流出时触发"""
        self.accumulated_response += token

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """流式调用结束时统计"""
        try:
            if response.llm_output:
                usage = response.llm_output.get("usage", {})

                input_tokens = usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0) or usage.get("output_tokens", 0)

                token_counter.record_tokens(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    model_name=self.model_name,
                    response=self.accumulated_response[:500],
                    session_id=self.session_id,
                    metadata={"handler": "streaming"}
                )

                logger.debug(
                    f"[StreamingTokenCallback] Total tokens: {input_tokens + output_tokens}"
                )
        except Exception as e:
            logger.error(f"[StreamingTokenCallback] 处理token时出错: {str(e)}")