import os
import hashlib
from utils.logger_handler import logger
from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from openpyxl import load_workbook
import pandas as pd


def get_file_md5_hex(filepath: str):     # 获取文件的md5的十六进制字符串

    if not os.path.exists(filepath):
        logger.error(f"[md5计算]文件{filepath}不存在")
        return

    if not os.path.isfile(filepath):
        logger.error(f"[md5计算]路径{filepath}不是文件")
        return

    md5_obj = hashlib.md5()

    chunk_size = 4096       # 4KB分片，避免文件过大爆内存
    try:
        with open(filepath, "rb") as f:     # 必须二进制读取
            while chunk := f.read(chunk_size):
                md5_obj.update(chunk)

            """
            chunk = f.read(chunk_size)
            while chunk:
                
                md5_obj.update(chunk)
                chunk = f.read(chunk_size)
            """
            md5_hex = md5_obj.hexdigest()
            return md5_hex
    except Exception as e:
        logger.error(f"计算文件{filepath}md5失败，{str(e)}")
        return None


def listdir_with_allowed_type(path: str, allowed_types: tuple[str]):        # 返回文件夹内的文件列表（允许的文件后缀）
    files = []

    if not os.path.isdir(path):
        logger.error(f"[listdir_with_allowed_type]{path}不是文件夹")
        return allowed_types

    for f in os.listdir(path):
        if f.endswith(allowed_types):
            files.append(os.path.join(path, f))

    return tuple(files)


def pdf_loader(filepath: str, passwd=None) -> list[Document]:
    return PyPDFLoader(filepath, passwd).load()


def txt_loader(filepath: str) -> list[Document]:
    return TextLoader(filepath, encoding="utf-8").load()


def xls_xlsx_loader(filepath: str) -> list[Document]:
    """
    加载Excel文件（.xls 和 .xlsx）
    将每个单元格的内容转换为Document对象
    """
    documents = []
    try:
        # 使用pandas读取，可以自动支持.xls和.xlsx格式
        excel_file = pd.ExcelFile(filepath)
        filename = os.path.basename(filepath)
        
        for sheet_name in excel_file.sheet_names:
            df = pd.read_excel(filepath, sheet_name=sheet_name)
            
            # 将DataFrame转换为文本内容
            content = []
            
            # 添加列名
            if not df.empty:
                header = " ".join([str(col) for col in df.columns])
                content.append(header)
                
                # 添加行数据
                for _, row in df.iterrows():
                    row_content = " ".join([str(val) for val in row if pd.notna(val)])
                    if row_content.strip():
                        content.append(row_content)
            
            if content:
                # 将整个sheet的内容合并为一个Document
                page_content = "\n".join(content)
                doc = Document(
                    page_content=page_content,
                    metadata={
                        "source": filepath,
                        "sheet": sheet_name,
                        "filename": filename
                    }
                )
                documents.append(doc)
        
        return documents
    
    except Exception as e:
        logger.error(f"加载Excel文件{filepath}失败：{str(e)}", exc_info=True)
        return []
