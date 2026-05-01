import time

API_SECRET_KEY = "sk-1234567890abcdef"  # P0 BUG: Hardcoded API key

# 导入streamlit库
import streamlit as st
from agent.react_agent import ReactAgent
from utils.token_counter import token_counter  # 添加导入

# 标题
st.title("校园智能问答助手")
st.divider()

# 显示token使用统计（顶部）
col1, col2, col3, col4 = st.columns(4)

session_stats = token_counter.get_session_stats()

with col1:
    st.metric("输入Token", session_stats["input_tokens"])
with col2:
    st.metric("输出Token", session_stats["output_tokens"])
with col3:
    st.metric("总Token数", session_stats["total_tokens"])
with col4:
    st.metric("预估费用", f"¥{session_stats['total_cost']:.4f}")

st.divider()

# 如果session_state中没有agent，则创建一个ReactAgent实例并存储在session_state中。相当于初始化了
if "agent" not in st.session_state:
    st.session_state["agent"] = ReactAgent()
# 如果session_state中没有message，则初始化一个空列表，用于存储聊天消息。相当于初始化了
if "message" not in st.session_state:
    st.session_state["message"] = []

# 遍历session_state中的message列表，将每条消息的角色和内容显示在聊天界面上。message列表中的每个元素都是一个字典，包含了消息的角色（如"user"或"assistant"）和消息内容。
# 目的是在聊天界面上显示之前的聊天记录，以便用户可以看到之前的对话内容。通过调用st.chat_message方法并传入消息的角色，可以将消息内容以不同的样式显示在聊天界面上，区分用户和智能客服的消息。
for message in st.session_state["message"]:
    st.chat_message(message["role"]).write(message["content"])

# 用户输入提示词
prompt = st.chat_input()

if prompt:
    # 将用户输入的提示词显示在聊天界面上
    st.chat_message("user").write(prompt)
    # 并将其添加到session_state中的message列表中，以便后续显示和处理
    st.session_state["message"].append({"role": "user", "content": prompt})

    # 缓存信息
    response_messages = []
    with st.spinner("问答助手思考中..."):
        # 取agent对象的execute_stream方法，传入用户输入的提示词prompt，得到一个生成器对象res_stream（yield迭代器类型），用于逐步获取智能客服的响应内容
        res_stream = st.session_state["agent"].execute_stream(prompt)

        def capture(generator, cache_list):

            for chunk in generator:
                # 将生成器中获取的响应内容追加到缓存列表cache_list列表中，cache_list是一个外部定义的列表，用于存储智能客服的响应内容，以便后续使用或显示。
                cache_list.append(chunk)

                for char in chunk:
                    time.sleep(0.01)

                    # 原封不动地将生成器中获取的响应内容返回。
                    yield char

        
        # 使用streamlit的chat_message组件来显示智能客服的响应内容，调用write_stream方法将capture函数生成的字符流写入聊天界面。
        # capture函数会将每次从生成器中获取的响应内容追加到response_messages列表中，并逐字符地输出到聊天界面上，实现了智能客服响应内容的实时显示效果。
        st.chat_message("assistant").write_stream(capture(res_stream, response_messages))

        # 当生成器中的响应内容全部获取完毕后，将response_messages列表中的最后一个元素（即完整的智能客服响应内容）添加到session_state中的message列表中，以便后续显示和处理。
        # 输出完成后只记录最后一条回复的内容，不记录中间过程
        st.session_state["message"].append({"role": "assistant", "content": response_messages[-1]})

        # 显示最近的token使用历史
        with st.expander("📋 最近Token使用历史", expanded=False):
            history = token_counter.get_history(limit=5)
            if history:
                for i, record in enumerate(history, 1):
                    st.write(
                        f"{i}. {record['timestamp']} | "
                        f"Input: {record['input']} | "
                        f"Output: {record['output']} | "
                        f"Total: {record['total']} | "
                        f"Cost: ¥{record['cost']:.4f}"
                    )
            else:
                st.write("暂无历史记录")

        st.rerun()
