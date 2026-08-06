import sqlite3
import json
import threading
import uuid
from typing import Optional, List, Dict, Any
from contextlib import contextmanager
from datetime import datetime

from .packet import InfoPacket, PacketType


class InfoManager:
    """
    信息管理器，负责信息包的持久化存储、查询和管理。
    
    基于 SQLite 实现，支持线程安全的并发访问，提供多种查询方式
    包括按 ID、发送者、父包、链、类型、内容关键字、元数据等查询。
    
    Attributes:
        db_path: 数据库文件路径，默认为内存数据库(":memory:")
    
    Example:
        # 创建内存数据库管理器
        manager = InfoManager()
        
        # 创建文件数据库管理器
        manager = InfoManager("/path/to/data.db")
        
        # 保存信息包
        manager.save(packet)
        
        # 按链查询
        packets = manager.get_by_chain_id("chain_123")
    """
    
    def __init__(self, db_path: str = ":memory:"):
        """
        初始化信息管理器。
        
        Args:
            db_path: 数据库文件路径，默认为内存数据库(":memory:")
        """
        self.db_path = db_path
        self._local = threading.local()
        self._lock = threading.RLock()
        self._use_uri = db_path == ":memory:"
        if self._use_uri:
            self._connection_target = f"file:agentflow_{uuid.uuid4().hex}?mode=memory&cache=shared"
        else:
            self._connection_target = db_path
        self._init_db()
    
    def _get_connection(self) -> sqlite3.Connection:
        """
        获取当前线程的数据库连接。
        
        每个线程拥有独立的数据库连接，确保线程安全。
        首次调用时会自动创建连接并初始化数据库表结构。
        
        Returns:
            sqlite3.Connection: 当前线程的数据库连接
        """
        if not hasattr(self._local, 'connection'):
            self._local.connection = sqlite3.connect(
                self._connection_target,
                uri=self._use_uri,
                timeout=30.0,
            )
            self._local.connection.row_factory = sqlite3.Row
            self._local.connection.execute("PRAGMA busy_timeout = 30000")
            # 启用 WAL 模式: 写入不阻塞读取, 减少 fsync 开销 (Windows HDD 5-20ms/次 → ~1ms)
            # synchronous=NORMAL: WAL 模式下安全, 减少 fsync 频率
            self._local.connection.execute("PRAGMA journal_mode = WAL")
            self._local.connection.execute("PRAGMA synchronous = NORMAL")
            self._init_db_for_connection(self._local.connection)
        return self._local.connection
    
    def _init_db_for_connection(self, conn: sqlite3.Connection):
        """
        为指定连接初始化数据库表结构和索引。
        
        创建 info_packets 表及常用查询字段的索引，包括：
        - sender_id: 发送者ID索引
        - parent_id: 父包ID索引
        - chain_id: 链ID索引
        - type: 包类型索引
        - timestamp: 时间戳索引
        
        Args:
            conn: SQLite 数据库连接
        """
        conn.execute('''
            CREATE TABLE IF NOT EXISTS info_packets (
                id TEXT PRIMARY KEY,
                sender_id TEXT NOT NULL,
                parent_id TEXT,
                chain_id TEXT NOT NULL,
                content TEXT,
                content_bytes BLOB,
                type TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                metadata TEXT
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_sender_id ON info_packets(sender_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_parent_id ON info_packets(parent_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_chain_id ON info_packets(chain_id)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_type ON info_packets(type)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_timestamp ON info_packets(timestamp)')
        conn.commit()
    
    def _init_db(self):
        """
        初始化数据库。
        
        获取连接时会自动初始化表结构，此方法用于确保数据库已就绪。
        """
        conn = self._get_connection()
    
    def save(self, packet: InfoPacket, auto_commit: bool = True) -> None:
        """
        保存信息包到数据库。
        
        STREAM 类型的包不会被保存。支持多种内容类型：
        - bytes: 存储到 content_bytes 字段
        - dict: 序列化为 JSON 存储到 content 字段
        - 其他: 直接存储到 content 字段
        
        Args:
            packet: 要保存的信息包
            auto_commit: 是否自动提交事务，默认为 True
        
        Example:
            manager.save(packet)
            
            # 批量保存时禁用自动提交
            with manager.transaction():
                for packet in packets:
                    manager.save(packet, auto_commit=False)
        """
        if packet.type == PacketType.STREAM:
            return
        
        with self._lock:
            conn = self._get_connection()
            
            content_text = None
            content_bytes = None
            
            if isinstance(packet.content, bytes):
                content_bytes = packet.content
            elif isinstance(packet.content, dict):
                content_text = json.dumps(packet.to_dict()['content'], ensure_ascii=False)
            else:
                content_text = packet.content
            
            metadata_json = json.dumps(packet.metadata, ensure_ascii=False)

            try:
                conn.execute('''
                    INSERT INTO info_packets 
                    (id, sender_id, parent_id, chain_id, content, content_bytes, type, timestamp, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    packet.id,
                    packet.sender_id,
                    packet.parent_id,
                    packet.chain_id,
                    content_text,
                    content_bytes,
                    packet.type.value,
                    packet.timestamp.isoformat(),
                    metadata_json
                ))
            except sqlite3.IntegrityError as exc:
                raise ValueError(
                    f"InfoManager.save() failed for packet '{packet.id}': {exc}"
                ) from exc

            if auto_commit:
                conn.commit()
    
    def _row_to_packet(self, row: sqlite3.Row) -> InfoPacket:
        """
        将数据库行转换为 InfoPacket 对象。
        
        自动处理内容类型的反序列化：
        - content_bytes 不为空: 返回 bytes
        - content 为 JSON 对象: 返回 dict
        - 其他: 返回字符串
        
        Args:
            row: SQLite 查询结果行
        
        Returns:
            InfoPacket: 转换后的信息包对象
        """
        content = row['content']
        if row['content_bytes'] is not None:
            content = row['content_bytes']
        elif row['content'] is not None:
            try:
                parsed = json.loads(row['content'])
                if isinstance(parsed, dict):
                    content = parsed
            except (json.JSONDecodeError, TypeError):
                pass
        
        metadata = json.loads(row['metadata']) if row['metadata'] else {}
        
        return InfoPacket(
            id=row['id'],
            sender_id=row['sender_id'],
            parent_id=row['parent_id'],
            chain_id=row['chain_id'],
            content=content,
            type=PacketType(row['type']),
            timestamp=datetime.fromisoformat(row['timestamp']),
            _metadata=metadata
        )
    
    def get_by_id(self, id: str) -> Optional[InfoPacket]:
        """
        根据 ID 获取信息包。
        
        Args:
            id: 信息包唯一标识符
        
        Returns:
            InfoPacket: 找到的信息包，不存在则返回 None
        
        Example:
            packet = manager.get_by_id("packet_123")
            if packet:
                print(packet.content)
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                'SELECT * FROM info_packets WHERE id = ?',
                (id,)
            )
            row = cursor.fetchone()
        if row:
            return self._row_to_packet(row)
        return None
    
    def get_by_chain_id(self, chain_id: str) -> List[InfoPacket]:
        """
        根据链 ID 获取该链上的所有信息包，按时间戳排序。
        
        Args:
            chain_id: 链唯一标识符
        
        Returns:
            List[InfoPacket]: 该链上的所有信息包列表
        
        Example:
            packets = manager.get_by_chain_id("chain_123")
            for packet in packets:
                print(f"{packet.timestamp}: {packet.content}")
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                'SELECT * FROM info_packets WHERE chain_id = ? ORDER BY timestamp',
                (chain_id,)
            )
            rows = cursor.fetchall()
        return [self._row_to_packet(row) for row in rows]
    
    def get_by_sender_id(self, sender_id: str) -> List[InfoPacket]:
        """
        根据发送者 ID 获取该发送者的所有信息包，按时间戳排序。
        
        Args:
            sender_id: 发送者唯一标识符
        
        Returns:
            List[InfoPacket]: 该发送者的所有信息包列表
        
        Example:
            packets = manager.get_by_sender_id("agent_001")
            print(f"Agent 001 发送了 {len(packets)} 条消息")
        """
        conn = self._get_connection()
        cursor = conn.execute(
            'SELECT * FROM info_packets WHERE sender_id = ? ORDER BY timestamp',
            (sender_id,)
        )
        return [self._row_to_packet(row) for row in cursor.fetchall()]
    
    def get_by_parent_id(self, parent_id: str) -> List[InfoPacket]:
        """
        根据父包 ID 获取所有子信息包，按时间戳排序。
        
        Args:
            parent_id: 父包唯一标识符
        
        Returns:
            List[InfoPacket]: 该父包的所有子信息包列表
        
        Example:
            replies = manager.get_by_parent_id("parent_packet_123")
            for reply in replies:
                print(f"回复: {reply.content}")
        """
        conn = self._get_connection()
        cursor = conn.execute(
            'SELECT * FROM info_packets WHERE parent_id = ? ORDER BY timestamp',
            (parent_id,)
        )
        return [self._row_to_packet(row) for row in cursor.fetchall()]
    
    def get_by_type(self, packet_type: PacketType) -> List[InfoPacket]:
        """
        根据类型获取所有信息包，按时间戳排序。
        
        Args:
            packet_type: 信息包类型 (PacketType.CALL, PacketType.RESPONSE, 等)
        
        Returns:
            List[InfoPacket]: 该类型的所有信息包列表
        
        Example:
            errors = manager.get_by_type(PacketType.ERROR)
            for error in errors:
                print(f"错误: {error.content}")
        """
        conn = self._get_connection()
        cursor = conn.execute(
            'SELECT * FROM info_packets WHERE type = ? ORDER BY timestamp',
            (packet_type.value,)
        )
        return [self._row_to_packet(row) for row in cursor.fetchall()]
    
    def search_by_content(self, keyword: str) -> List[InfoPacket]:
        """
        根据内容关键字搜索信息包，按时间戳排序。
        
        使用 SQL LIKE 进行模糊匹配，支持通配符 % 和 _。
        
        Args:
            keyword: 搜索关键字
        
        Returns:
            List[InfoPacket]: 内容匹配的信息包列表
        
        Example:
            results = manager.search_by_content("error")
            results = manager.search_by_content("%pattern%")
        """
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT * FROM info_packets WHERE content LIKE ? ORDER BY timestamp",
            (f'%{keyword}%',)
        )
        return [self._row_to_packet(row) for row in cursor.fetchall()]
    
    def search_by_metadata(self, key: str, value: Any) -> List[InfoPacket]:
        """
        根据元数据键值对搜索信息包，按时间戳排序。
        
        由于元数据以 JSON 格式存储，此方法会遍历所有记录进行匹配。
        对于大量数据，建议结合其他查询条件使用 query() 方法。
        
        Args:
            key: 元数据键名
            value: 元数据值
        
        Returns:
            List[InfoPacket]: 元数据匹配的信息包列表
        
        Example:
            results = manager.search_by_metadata("priority", "high")
            results = manager.search_by_metadata("source", "user_input")
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                'SELECT * FROM info_packets ORDER BY timestamp'
            )
            rows = cursor.fetchall()

        results = []
        for row in rows:
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            if metadata.get(key) == value:
                results.append(self._row_to_packet(row))
        
        return results
    
    def query(self, **kwargs) -> List[InfoPacket]:
        """
        多条件组合查询信息包。
        
        支持的条件参数：
        - sender_id: 发送者 ID
        - parent_id: 父包 ID
        - chain_id: 链 ID
        - type: 包类型 (PacketType 或字符串)
        - start_time: 开始时间 (datetime 对象)
        - end_time: 结束时间 (datetime 对象)
        - metadata: 元数据字典，用于精确匹配
        
        所有条件之间为 AND 关系，结果按时间戳排序。
        
        Args:
            **kwargs: 查询条件关键字参数
        
        Returns:
            List[InfoPacket]: 符合条件的信息包列表
        
        Example:
            # 查询特定链的所有消息
            packets = manager.query(chain_id="chain_123")
            
            # 查询特定发送者在时间范围内的消息
            packets = manager.query(
                sender_id="agent_001",
                start_time=datetime(2024, 1, 1),
                end_time=datetime(2024, 12, 31)
            )
            
            # 多条件组合查询
            packets = manager.query(
                chain_id="chain_123",
                type=PacketType.RESPONSE,
                metadata={"status": "completed"}
            )
        """
        conn = self._get_connection()
        
        conditions = []
        params = []
        
        if 'sender_id' in kwargs:
            conditions.append('sender_id = ?')
            params.append(kwargs['sender_id'])
        
        if 'parent_id' in kwargs:
            conditions.append('parent_id = ?')
            params.append(kwargs['parent_id'])
        
        if 'chain_id' in kwargs:
            conditions.append('chain_id = ?')
            params.append(kwargs['chain_id'])
        
        if 'type' in kwargs:
            packet_type = kwargs['type']
            if isinstance(packet_type, PacketType):
                conditions.append('type = ?')
                params.append(packet_type.value)
            else:
                conditions.append('type = ?')
                params.append(packet_type)
        
        if 'start_time' in kwargs:
            conditions.append('timestamp >= ?')
            params.append(kwargs['start_time'].isoformat())
        
        if 'end_time' in kwargs:
            conditions.append('timestamp <= ?')
            params.append(kwargs['end_time'].isoformat())
        
        if conditions:
            sql = f"SELECT * FROM info_packets WHERE {' AND '.join(conditions)} ORDER BY timestamp"
        else:
            sql = "SELECT * FROM info_packets ORDER BY timestamp"
        
        cursor = conn.execute(sql, params)
        results = [self._row_to_packet(row) for row in cursor.fetchall()]
        
        if 'metadata' in kwargs:
            meta_filter = kwargs['metadata']
            filtered_results = []
            for packet in results:
                match = True
                for key, value in meta_filter.items():
                    if packet.get_metadata(key) != value:
                        match = False
                        break
                if match:
                    filtered_results.append(packet)
            results = filtered_results
        
        return results
    
    @contextmanager
    def transaction(self):
        """
        事务上下文管理器，用于批量操作。
        
        在事务中执行多个 save() 操作时应设置 auto_commit=False，
        事务提交时会统一提交，发生异常时自动回滚。
        
        Yields:
            sqlite3.Connection: 数据库连接对象
        
        Example:
            with manager.transaction():
                for packet in packets:
                    manager.save(packet, auto_commit=False)
            # 事务自动提交
            
            # 异常时自动回滚
            try:
                with manager.transaction():
                    manager.save(packet1, auto_commit=False)
                    raise Exception("出错")
                    manager.save(packet2, auto_commit=False)
            except Exception:
                # packet1 的保存被回滚
                pass
        """
        conn = self._get_connection()
        original_isolation = conn.isolation_level
        conn.isolation_level = None
        conn.execute('BEGIN')
        try:
            yield conn
            conn.execute('COMMIT')
        except Exception:
            conn.execute('ROLLBACK')
            raise
        finally:
            conn.isolation_level = original_isolation
    
    def execute_query(self, sql: str, params: tuple = ()) -> List[InfoPacket]:
        """
        执行只读 SQL 查询，返回 InfoPacket 对象列表。
        
        此接口仅允许 SELECT 查询，会自动拦截任何增删改操作
        (INSERT, UPDATE, DELETE, DROP, CREATE, ALTER 等)。
        
        Args:
            sql: SQL 查询语句，必须以 SELECT 开头
            params: SQL 参数元组，用于参数化查询
        
        Returns:
            List[InfoPacket]: 查询结果转换后的信息包列表
        
        Raises:
            ValueError: 当 SQL 不是以 SELECT 开头的只读查询时
        
        Example:
            # 基础查询
            packets = manager.execute_query(
                "SELECT * FROM info_packets WHERE sender_id = ?",
                ("agent_001",)
            )
            
            # 复杂条件查询
            packets = manager.execute_query('''
                SELECT * FROM info_packets 
                WHERE type = ? AND timestamp > ?
                ORDER BY timestamp DESC
                LIMIT 10
            ''', ("call", "2024-01-01T00:00:00"))
            
            # 以下操作会被拦截并抛出 ValueError:
            # manager.execute_query("DELETE FROM info_packets")
            # manager.execute_query("UPDATE info_packets SET type = 'test'")
            # manager.execute_query("INSERT INTO info_packets ...")
        """
        # 提取 SQL 语句的关键字部分（去除前导空白和注释）
        sql_stripped = sql.strip()
        
        # 移除前导注释（-- 或 /* */）
        while sql_stripped:
            if sql_stripped.startswith('--'):
                # 跳过单行注释
                newline_pos = sql_stripped.find('\n')
                if newline_pos == -1:
                    sql_stripped = ''
                else:
                    sql_stripped = sql_stripped[newline_pos + 1:].strip()
            elif sql_stripped.startswith('/*'):
                # 跳过多行注释
                end_pos = sql_stripped.find('*/')
                if end_pos == -1:
                    sql_stripped = ''
                else:
                    sql_stripped = sql_stripped[end_pos + 2:].strip()
            else:
                break
        
        # 检查是否为只读查询（必须以 SELECT 开头）
        first_keyword = sql_stripped[:6].upper()
        if first_keyword != 'SELECT':
            raise ValueError(
                f"只允许 SELECT 查询，检测到非法操作: {sql_stripped[:20]}..."
            )
        
        # 额外的安全检查：检测常见的增删改关键字
        dangerous_keywords = [
            'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER',
            'TRUNCATE', 'REPLACE', 'MERGE', 'UPSERT'
        ]
        
        sql_upper = sql_stripped.upper()
        for keyword in dangerous_keywords:
            # 使用正则表达式风格的关键字检测，确保是完整单词
            import re
            pattern = r'\b' + keyword + r'\b'
            if re.search(pattern, sql_upper):
                raise ValueError(
                    f"检测到危险操作关键字 '{keyword}'，只允许 SELECT 查询"
                )
        
        conn = self._get_connection()
        cursor = conn.execute(sql, params)
        return [self._row_to_packet(row) for row in cursor.fetchall()]
    
    def close(self):
        """
        关闭当前线程的数据库连接。
        
        应在不再使用管理器时调用，释放资源。
        每个线程的连接需要分别关闭。
        
        Example:
            manager.close()
        """
        if hasattr(self._local, 'connection'):
            self._local.connection.close()
            del self._local.connection

    def delete_by_chain_id(self, chain_id: str, auto_commit: bool = True) -> int:
        """
        删除指定链上的所有信息包。

        Returns:
            int: 删除的记录数
        """
        conn = self._get_connection()
        cursor = conn.execute(
            'DELETE FROM info_packets WHERE chain_id = ?',
            (chain_id,)
        )
        if auto_commit:
            conn.commit()
        return cursor.rowcount

    def truncate_chain_after_packet(
        self,
        chain_id: str,
        packet_id: str,
        *,
        inclusive: bool = False,
        auto_commit: bool = True,
    ) -> int:
        """
        删除指定链上某条 packet 之后的所有消息。

        默认保留当前 packet，仅删除它之后的内容；如果 `inclusive=True`，
        则会连同当前 packet 一起删除。
        """
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                'SELECT id FROM info_packets WHERE chain_id = ? ORDER BY timestamp, rowid',
                (chain_id,),
            )
            packet_ids = [str(row['id']) for row in cursor.fetchall()]

            if packet_id not in packet_ids:
                return 0

            pivot_index = packet_ids.index(packet_id)
            start_index = pivot_index if inclusive else pivot_index + 1
            delete_ids = packet_ids[start_index:]
            if not delete_ids:
                return 0

            placeholders = ', '.join('?' for _ in delete_ids)
            delete_cursor = conn.execute(
                f'DELETE FROM info_packets WHERE id IN ({placeholders})',
                tuple(delete_ids),
            )
            if auto_commit:
                conn.commit()
            return delete_cursor.rowcount

    def delete_by_ids(self, packet_ids: List[str], auto_commit: bool = True) -> int:
        """
        按 packet id 批量删除消息。

        Args:
            packet_ids: 需要删除的 packet id 列表
            auto_commit: 是否自动提交事务

        Returns:
            int: 实际删除的记录数
        """
        if not packet_ids:
            return 0

        with self._lock:
            conn = self._get_connection()
            placeholders = ", ".join("?" for _ in packet_ids)
            cursor = conn.execute(
                f"DELETE FROM info_packets WHERE id IN ({placeholders})",
                tuple(packet_ids),
            )
            if auto_commit:
                conn.commit()
            return cursor.rowcount
