#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
向量数据库重建脚本
"""
import sys
from rag.vector_store import VectorStoreService
from utils.logger_handler import logger

if __name__ == '__main__':
    try:
        logger.info("开始重建向量数据库...")
        vs = VectorStoreService()
        vs.load_document()
        logger.info("✅ 向量数据库重建完成！")
        print("✅ 向量数据库重建完成！")
        sys.exit(0)
    except Exception as e:
        logger.error(f"❌ 向量数据库重建失败：{str(e)}", exc_info=True)
        print(f"❌ 向量数据库重建失败：{str(e)}")
        sys.exit(1)
