from langchain_chroma import Chroma
from langchain_core.documents import Document
# 导入
from utils.config_handler import chroma_conf
# 导入模型工厂中的文本嵌入模型
from model.factory import embed_model
# 导入文本分块工具 递归文本分割器，用于将长文本分割成更小的块，以便进行向量化处理。
from langchain_text_splitters import RecursiveCharacterTextSplitter
from utils.path_tool import get_abs_path
from utils.file_handler import pdf_loader, txt_loader, xls_xlsx_loader, listdir_with_allowed_type, get_file_md5_hex
from utils.logger_handler import logger
import os


class VectorStoreService:
    def __init__(self):
        self.vector_store = Chroma(
            # collection_name是向量库中一个逻辑上的分类，
            # 可以理解为数据库中的表名或者文件系统中的文件夹名，
            # 用于区分不同类型的文档集合。
            # 在这个代码中，collection_name的值来自于配置文件中的chroma_conf["collection_name"]，表示要使用的向量库集合名称。
            collection_name=chroma_conf["collection_name"],

            # embedding_function参数指定了用于生成文本向量的嵌入模型实例，这个实例是通过调用模型工厂中的EmbeddingsFactory类的generator()方法创建的。
            embedding_function=embed_model,
            persist_directory=chroma_conf["persist_directory"],
        )

        # 文本分割器
        self.spliter = RecursiveCharacterTextSplitter(
            chunk_size=chroma_conf["chunk_size"],
            chunk_overlap=chroma_conf["chunk_overlap"],
            # 分割符
            separators=chroma_conf["separators"],
            length_function=len,
        )

    # 获取检索器对象
    # 需要传参数k，指定每次检索返回的相关文档数量k，这个值来自于配置文件中的chroma_conf["k"]。
    def get_retriever(self):
        return self.vector_store.as_retriever(search_kwargs={"k": chroma_conf["k"]})

    # 从数据文件夹内读取数据文件，转为向量存入向量库
    def load_document(self):
        """
        从数据文件夹内读取数据文件，转为向量存入向量库
        过程中要计算文件的MD5做去重
        :return: None
        """

        # 该函数用于检查给定的MD5值是否已经存在于记录文件中，以判断对应的文件内容是否已经被处理过。
        def check_md5_hex(md5_for_check: str):
            # 如果记录MD5值的文件不存在，说明还没有任何文件被处理过，因此返回False。
            # 这里拿到的是相对路径 需要转成绝对路径
            if not os.path.exists(get_abs_path(chroma_conf["md5_hex_store"])):
                # 创建文件
                open(get_abs_path(chroma_conf["md5_hex_store"]), "w", encoding="utf-8").close()
                return False            # md5 没处理过

            # 如果记录MD5值的文件存在，则打开该文件并逐行读取其中的MD5值，检查是否有与传入的md5_for_check相匹配的值。
            # 如果找到匹配的值，说明对应的文件内容已经被处理过，函数返回True；如果遍历完整个文件都没有找到匹配的值，则说明该MD5值还没有被处理过，函数返回False。
            with open(get_abs_path(chroma_conf["md5_hex_store"]), "r", encoding="utf-8") as f:
                for line in f.readlines():
                    # strip()方法用于去除字符串两端的空白字符，包括换行符、制表符和空格等，以确保在比较MD5值时不会因为多余的空白字符而导致错误的结果。
                    line = line.strip()
                    # 如果当前行的MD5值与传入的md5_for_check相匹配，说明该文件内容已经被处理过，函数返回True。
                    if line == md5_for_check:
                        return True     # md5 处理过

                return False            # md5 没处理过

        # 保存md5
        def save_md5_hex(md5_for_check: str):
            # 
            with open(get_abs_path(chroma_conf["md5_hex_store"]), "a", encoding="utf-8") as f:
                f.write(md5_for_check + "\n")

        # 根据文件路径获取文件内容并转换为Document对象列表，支持txt、pdf、xls和xlsx四种文件类型。
        # 如果文件类型不受支持，则返回一个空列表。
        def get_file_documents(read_path: str):
            # 支持从外部路径加载文档
            resolved = read_path
            if read_path.endswith("txt"):
                return txt_loader(resolved)

            if read_path.endswith("pdf"):
                return pdf_loader(resolved)

            if read_path.endswith((".xls", ".xlsx")):
                return xls_xlsx_loader(resolved)

            return []
        #
        allowed_files_path: list[str] = listdir_with_allowed_type(
            get_abs_path(chroma_conf["data_path"]),
            tuple(chroma_conf["allow_knowledge_file_type"]),
        )

        # 支持从外部指定额外的文档路径
        extra_path = os.environ.get("EXTRA_DOC_PATH")
        if extra_path:
            allowed_files_path.append(extra_path)

        for path in allowed_files_path:
            # 获取文件的MD5
            md5_hex = get_file_md5_hex(path)

            if check_md5_hex(md5_hex):
                logger.info(f"[加载知识库]{path}内容已经存在知识库内，跳过")
                continue

            try:
                documents: list[Document] = get_file_documents(path)

                if not documents:
                    logger.warning(f"[加载知识库]{path}内没有有效文本内容，跳过")
                    continue

                split_document: list[Document] = self.spliter.split_documents(documents)

                if not split_document:
                    logger.warning(f"[加载知识库]{path}分片后没有有效文本内容，跳过")
                    continue

                # 将内容存入向量库
                self.vector_store.add_documents(split_document)

                # 记录这个已经处理好的文件的md5，避免下次重复加载
                save_md5_hex(md5_hex)

                logger.info(f"[加载知识库]{path} 内容加载成功")
            except Exception as e:
                # exc_info为True会记录详细的报错堆栈，如果为False仅记录报错信息本身
                logger.error(f"[加载知识库]{path}加载失败：{str(e)}", exc_info=True)
                continue


if __name__ == '__main__':
    vs = VectorStoreService()

    vs.load_document()

    retriever = vs.get_retriever()

    res = retriever.invoke("迷路")
    for r in res:
        print(r.page_content)
        print("-"*20)


