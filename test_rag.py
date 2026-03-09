#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试RAG检索功能
"""
import sys
sys.path.insert(0, 'c:\\Users\\30295\\Desktop\\langchain')

try:
    from rag.rag_service import RagSummarizeService
    from rag.vector_store import VectorStoreService
    
    print("=" * 50)
    print("测试向量库检索")
    print("=" * 50)
    
    # 测试向量库
    vs = VectorStoreService()
    retriever = vs.get_retriever()
    
    # 测试查询
    query = "大二要上哪些课"
    print(f"\n查询：{query}")
    print("-" * 50)
    
    docs = retriever.invoke(query)
    print(f"检索到 {len(docs)} 份文档：\n")
    
    for i, doc in enumerate(docs, 1):
        print(f"【文档 {i}】")
        print(f"来源：{doc.metadata}")
        print(f"内容（前200字）：{doc.page_content[:200]}")
        print("-" * 50)
    
    # 测试RAG总结
    print("\n" + "=" * 50)
    print("测试RAG总结功能")
    print("=" * 50)
    
    rag = RagSummarizeService()
    result = rag.rag_summarize(query)
    print(f"\nRAG总结结果：\n{result}")
    
except Exception as e:
    print(f"❌ 测试失败：{str(e)}")
    import traceback
    traceback.print_exc()
