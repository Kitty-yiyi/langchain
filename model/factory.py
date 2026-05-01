# 模型工厂代码

from abc import ABC, abstractmethod
from typing import Optional
from langchain_core.embeddings import Embeddings
from langchain_community.chat_models.tongyi import BaseChatModel
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.chat_models.tongyi import ChatTongyi

# 从配置文件中导入rag_conf配置项，包含了聊天模型和嵌入模型的名称等相关配置。
from utils.config_handler import rag_conf
from model.token_callback import TokenCountingCallbackHandler  # 添加导入


# 基础抽象类BaseModelFactory定义了一个抽象方法generator()，用于生成模型实例。
# ChatModelFactory和EmbeddingsFactory分别继承自BaseModelFactory，实现了generator()方法来生成聊天模型和嵌入模型的实例。
# 最后，通过调用工厂类的generator()方法，创建了chat_model和embed_model两个模型实例，供后续使用。
class BaseModelFactory(ABC):
    @abstractmethod
    # Embeddings是用于生成文本向量的模型，
    # BaseChatModel是用于生成聊天回复的模型，
    # 这两个类型都是可选的，表示生成的模型实例可能是其中之一，也可能是两者都不是。
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        pass

# ChatModelFactory是一个工厂类，用于生成聊天模型实例。
# 它继承自BaseModelFactory，并实现了generator()方法来创建一个ChatTongyi聊天模型实例，
# 模型名称来自于配置文件中的rag_conf["chat_model_name"]。
class ChatModelFactory(BaseModelFactory):
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        # 创建token计数回调处理器
        token_callback = TokenCountingCallbackHandler(
            model_name=rag_conf["chat_model_name"]
        )

        # 创建ChatTongyi模型并添加回调
        return ChatTongyi(
            model=rag_conf["chat_model_name"],
            callbacks=[token_callback],  # 添加回调列表
        )

# EmbeddingsFactory是一个工厂类，用于生成嵌入模型实例。
# 它继承自BaseModelFactory，并实现了generator()方法来创建一个DashScopeEmbeddings嵌入模型实例，
# 模型名称来自于配置文件中的rag_conf["embedding_model_name"]。
class EmbeddingsFactory(BaseModelFactory):
    def generator(self) -> Optional[Embeddings | BaseChatModel]:
        return DashScopeEmbeddings(model=rag_conf["embedding_model_name"])


chat_model = ChatModelFactory().generator()
embed_model = EmbeddingsFactory().generator()
