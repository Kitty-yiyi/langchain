import time
import json
import sqlite3
import numpy as np
import faiss
from collections import OrderedDict

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

from rag.vector_store import VectorStoreService
from model.factory import chat_model, embed_model


class RagSummarizeService:

    def __init__(self):
        self.vector_store = VectorStoreService()
        self.retriever = self.vector_store.get_retriever()
        self.model = chat_model
        self.embed_model = embed_model

        # ===== Prompt（基于检索上下文回答）=====
        self.prompt = PromptTemplate.from_template("""
你是校园智能问答助手，负责结合校园知识库资料回答学生问题。

规则：
- 如果问题只是寒暄、致谢或询问你的身份，可以直接简短回答
- 如果上下文中有相关资料，必须优先基于上下文回答
- 如果上下文为空，或上下文无法回答问题，直接回答：我不知道
- 不要编造知识库中没有的政策、课程、日期、地点或联系方式
- 回答要简洁、自然，适合大学生阅读

问题：
{input}

上下文：
{context}

请给出最终答案：
""")

        self.chain = self.prompt | self.model | StrOutputParser()

        # ===== DB =====
        self.db_path = 'rag_cache.db'
        self.ttl = 3600

        # ===== FAISS（语义缓存）=====
        self.dimension = len(self.embed_model.embed_query("test"))
        self.index = faiss.IndexFlatIP(self.dimension)

        self.index_to_query = []
        self.meta = {}

        # ===== 精确缓存 =====
        self.exact_cache = OrderedDict()

        # ===== Tool Cache（新）=====
        self.tool_cache = {}

        self._init_db()

    def _get_db_connection(self):
        """获取数据库连接（线程安全）"""
        return sqlite3.connect(self.db_path, check_same_thread=False)

    def _init_db(self):
        """初始化数据库"""
        conn = self._get_db_connection()
        cursor = conn.cursor()

        # ===== 初始化数据库表 =====
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cache (
            query TEXT PRIMARY KEY,
            docs TEXT,
            answer TEXT,
            vector TEXT,
            timestamp REAL
        )
        """)
        conn.commit()
        conn.close()

        self._load()

    # ================= 基础 =================

    def _normalize(self, v):
        v = np.array(v, dtype=np.float32)
        return v / np.linalg.norm(v)

    def _clean(self, q):
        return q.strip().lower()

    def _build_context(self, docs):
        return "\n".join([d.page_content for d in docs])

    # ================= 加载 =================

    def _load(self):
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT query, docs, answer, vector, timestamp FROM cache")
        rows = cursor.fetchall()
        conn.close()

        now = time.time()
        vectors = []

        for q, docs, ans, vec, ts in rows:
            if now - ts > self.ttl:
                continue

            v = json.loads(vec)
            vectors.append(v)

            self.index_to_query.append(q)
            self.meta[q] = {"docs": docs, "answer": ans}

            self.exact_cache[q] = ans

        if vectors:
            vecs = np.array(vectors, dtype=np.float32)
            vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
            self.index.add(vecs)

    # ================= Tool Cache =================

    def _retrieve_with_cache(self, query):
        """RAG + Tool缓存"""

        if query in self.tool_cache:
            print("🧰 Tool Cache 命中")
            return self.tool_cache[query]

        docs = self.retriever.invoke(query)
        self.tool_cache[query] = docs  # 无上限写入，长期运行会导致内存持续增长
        return docs

    # ================= 主流程 =================

    def ask(self, query: str):

        query = self._clean(query)

        # ===== 1. 精确缓存 =====
        if query in self.exact_cache:
            print("✅ 精确缓存")
            return self.exact_cache[query]

        # ===== 2. 语义缓存 =====
        q_vec = self._normalize(self.embed_model.embed_query(query))
        q_vec_np = np.array([q_vec], dtype=np.float32)

        if self.index.ntotal > 0:
            D, I = self.index.search(q_vec_np, 3)

            for score, idx in zip(D[0], I[0]):
                if idx == -1:
                    continue

                cached_q = self.index_to_query[idx]
                sim = float(score)

                if sim > 0.92:
                    print("🔥 强语义缓存")
                    return self.meta[cached_q]["answer"]

                if sim > 0.85:
                    print("⚡ 弱语义缓存")
                    docs = json.loads(self.meta[cached_q]["docs"])
                    docs = [Document(**d) for d in docs]
                    context = self._build_context(docs)
                    return self.chain.invoke({"input": query, "context": context})

        # ===== 3. 判断是否需要RAG =====
        need_rag = self._need_rag(query)

        if need_rag:
            docs = self._retrieve_with_cache(query)
            context = self._build_context(docs)
        else:
            context = ""

        # ===== 4. LLM =====
        answer = self.chain.invoke({"input": query, "context": context})

        # ===== 5. 写缓存 =====
        # 写入缓存（并发场景下多个请求可能同时到达此处，导致重复写入）
        self._save(query, docs if need_rag else [], answer, q_vec)
        self.index.add(np.array([q_vec], dtype=np.float32))
        self.index_to_query.append(query)

        return answer

    # ================= 检索决策 =================

    def _need_rag(self, query: str) -> bool:
        """RAG工具默认检索校园知识库，只对明确寒暄或通用闲聊跳过。"""
        simple_queries = {
            "你好",
            "您好",
            "hello",
            "hi",
            "谢谢",
            "多谢",
            "你是谁",
            "介绍一下自己",
        }
        if query in simple_queries:
            return False

        campus_keywords = [
            "新生", "攻略", "华农", "生存指南", "培养方案", "信息学院", "课程",
            "通识", "选课", "学分", "毕业", "学位", "社团", "奖学金", "助学金",
            "宿舍", "食堂", "图书馆", "校历", "考试", "放假", "校园", "推荐",
            "不考试", "好过",
        ]
        if any(keyword in query for keyword in campus_keywords):
            return True

        question_indicators = ["什么", "哪些", "怎么", "如何", "为什么", "能不能", "是否", "吗", "？", "?"]
        if any(indicator in query for indicator in question_indicators):
            return True

        return True

    # ================= 存储 =================

    def _save(self, query, docs, answer, vec):

        docs_json = json.dumps(
            [{"page_content": d.page_content, "metadata": d.metadata} for d in docs],
            ensure_ascii=False
        )

        vec_json = json.dumps(vec.tolist(), ensure_ascii=False)

        now = time.time()

        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?, ?)",
            (query, docs_json, answer, vec_json, now)
        )
        conn.commit()
        conn.close()

        self.exact_cache[query] = answer

        self.index.add(np.array([vec], dtype=np.float32))
        self.index_to_query.append(query)
        self.meta[query] = {"docs": docs_json, "answer": answer}

    def rag_summarize(self, query: str):
        """RAG总结方法 - 兼容现有代码"""
        return self.ask(query)
