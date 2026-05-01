import sqlite3
import time
from typing import Dict, Optional
from datetime import datetime
from utils.logger_handler import logger

class TokenCounter:
    """管理token使用统计"""

    def __init__(self, db_path: str = "token_usage.db"):
        self.db_path = db_path
        self.current_session_tokens = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
        }
        self._init_db()

    def _get_connection(self):
        """获取数据库连接（线程安全）"""
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        """初始化数据库"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # 创建token使用记录表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            session_id TEXT,
            model_name TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            total_tokens INTEGER,
            cost REAL,
            prompt TEXT,
            response TEXT,
            metadata TEXT
        )
        """)

        # 创建每日统计表
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE UNIQUE,
            total_input_tokens INTEGER DEFAULT 0,
            total_output_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            total_cost REAL DEFAULT 0.0,
            conversation_count INTEGER DEFAULT 0
        )
        """)

        conn.commit()
        conn.close()

    def record_tokens(
        self,
        input_tokens: int,
        output_tokens: int,
        model_name: str,
        prompt: str = "",
        response: str = "",
        session_id: str = "",
        metadata: Dict = None,
    ):
        """记录单次token使用"""
        total_tokens = input_tokens + output_tokens

        # 更新当前会话统计
        self.current_session_tokens["input_tokens"] += input_tokens
        self.current_session_tokens["output_tokens"] += output_tokens
        self.current_session_tokens["total_tokens"] += total_tokens
        self.current_session_tokens["total_cost"] += self._calculate_cost(total_tokens)

        # 保存到数据库
        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO token_usage
        (session_id, model_name, input_tokens, output_tokens, total_tokens, cost, prompt, response, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            session_id,
            model_name,
            input_tokens,
            output_tokens,
            total_tokens,
            self._calculate_cost(total_tokens),
            prompt[:500] if prompt else "",
            response[:500] if response else "",
            str(metadata or {}),
        ))

        # 更新每日统计
        today = datetime.now().date()
        cursor.execute("""
        INSERT OR REPLACE INTO daily_stats
        (date, total_input_tokens, total_output_tokens, total_tokens, total_cost, conversation_count)
        VALUES (
            ?,
            COALESCE((SELECT total_input_tokens FROM daily_stats WHERE date = ?), 0) + ?,
            COALESCE((SELECT total_output_tokens FROM daily_stats WHERE date = ?), 0) + ?,
            COALESCE((SELECT total_tokens FROM daily_stats WHERE date = ?), 0) + ?,
            COALESCE((SELECT total_cost FROM daily_stats WHERE date = ?), 0) + ?,
            COALESCE((SELECT conversation_count FROM daily_stats WHERE date = ?), 0) + 1
        )
        """, (
            today, today, input_tokens,
            today, output_tokens,
            today, total_tokens,
            today, self._calculate_cost(total_tokens),
            today,
        ))

        conn.commit()
        conn.close()

        logger.info(f"[TokenCounter] 记录token: input={input_tokens}, output={output_tokens}, total={total_tokens}")

    @staticmethod
    def _calculate_cost(total_tokens: int) -> float:
        """计算成本（按千token计费，0.001元）"""
        return (total_tokens / 1000) * 0.001

    def get_session_stats(self) -> Dict:
        """获取当前会话统计"""
        return self.current_session_tokens.copy()

    def get_daily_stats(self, date: str = None) -> Optional[Dict]:
        """获取每日统计"""
        if date is None:
            date = datetime.now().date()

        conn = self._get_connection()
        cursor = conn.cursor()

        cursor.execute("""
        SELECT total_input_tokens, total_output_tokens, total_tokens, total_cost, conversation_count
        FROM daily_stats WHERE date = ?
        """, (str(date),))

        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                "date": str(date),
                "input_tokens": row[0],
                "output_tokens": row[1],
                "total_tokens": row[2],
                "cost": row[3],
                "conversation_count": row[4],
            }
        return None

    def get_history(self, limit: int = 10, session_id: str = None) -> list:
        """获取历史记录"""
        conn = self._get_connection()
        cursor = conn.cursor()

        if session_id:
            cursor.execute("""
            SELECT timestamp, model_name, input_tokens, output_tokens, total_tokens, cost
            FROM token_usage WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?
            """, (session_id, limit))
        else:
            cursor.execute("""
            SELECT timestamp, model_name, input_tokens, output_tokens, total_tokens, cost
            FROM token_usage ORDER BY timestamp DESC LIMIT ?
            """, (limit,))

        rows = cursor.fetchall()
        conn.close()

        return [
            {
                "timestamp": row[0],
                "model": row[1],
                "input": row[2],
                "output": row[3],
                "total": row[4],
                "cost": row[5],
            }
            for row in rows
        ]

    def reset_session(self):
        """重置会话统计"""
        self.current_session_tokens = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
        }


# 全局token计数器实例
token_counter = TokenCounter()