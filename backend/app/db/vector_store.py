# Personal RAG - FAISS 向量存储封装
"""
向量存储模块

基于 FAISS 实现向量索引，SQLite 存储元数据。
替代 ChromaDB，无需 C++ 编译工具，Windows 安装简单。

架构：
- FAISS IndexIDMap(IndexFlatIP): 存储归一化向量，内积搜索 = 余弦相似度
- SQLite chunks 表: 存储文本和元数据
- 磁盘持久化: FAISS index 序列化到 data/faiss/ 目录
"""

import os
import pickle
from pathlib import Path
from typing import Any, Optional

import numpy as np
import faiss

from app.config import settings


class VectorStore:
    """
    基于 FAISS + SQLite 的向量存储。

    使用 IndexIDMap 包装 IndexFlatIP 实现余弦相似度搜索。
    向量在添加时自动 L2 归一化。
    索引持久化到磁盘，支持重启恢复。

    Attributes:
        index_path: FAISS 索引文件路径
        dim: 向量维度 (nomic-embed-text: 768)
    """

    def __init__(self, dim: int = 768) -> None:
        """
        初始化 FAISS 向量存储。

        尝试从磁盘加载已有索引，如果不存在则创建新索引。

        Args:
            dim: 向量维度，默认 768 (nomic-embed-text 输出维度)
        """
        self.dim = dim
        self._index_dir = Path(settings.data_dir) / "faiss"
        self._index_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._index_dir / "rag_index.faiss"
        self._id_map_path = self._index_dir / "id_map.pkl"

        # 内部 ID → chunk_id 映射
        self._id_map: dict[int, str] = {} # <id, uuid>
        self._reverse_id_map: dict[str, int] = {} # <uuid, id>
        self._next_id: int = 0

        # 加载或创建 FAISS 索引
        if self._index_path.exists() and self._id_map_path.exists():
            self._load()
        else:
            self._create_new()

    @property
    def index(self) -> faiss.Index:
        """获取底层 FAISS 索引（用于直接操作）。"""
        return self._index

    def _create_new(self) -> None:
        """创建新的 FAISS 索引。使用内积 (Inner Product) 度量。"""
        # IndexFlatIP: 内积搜索 = 对归一化向量的余弦相似度
        quantizer = faiss.IndexFlatIP(self.dim)
        self._index = faiss.IndexIDMap(quantizer)

    def _load(self) -> None:
        """从磁盘加载 FAISS 索引和 ID 映射。"""
        self._index = faiss.read_index(str(self._index_path))
        with open(self._id_map_path, "rb") as f:
            data = pickle.load(f)
        self._id_map = data.get("id_map", {})
        self._reverse_id_map = data.get("reverse_id_map", {})
        self._next_id = data.get("next_id", 0)

    def _save(self) -> None:
        """将 FAISS 索引和 ID 映射持久化到磁盘。"""
        faiss.write_index(self._index, str(self._index_path))
        with open(self._id_map_path, "wb") as f:
            pickle.dump({
                "id_map": self._id_map,
                "reverse_id_map": self._reverse_id_map,
                "next_id": self._next_id,
            }, f)

    def _normalize(self, vectors: np.ndarray) -> np.ndarray:
        """
        L2 归一化向量，使内积搜索等价于余弦相似度。

        Args:
            vectors: shape (n, dim) 的 numpy 数组

        Returns:
            归一化后的向量
        """
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)  # 避免除零
        return vectors / norms

    def add_chunks(
        self,
        chunk_ids: list[str],
        texts: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """
        批量添加文档分块到向量索引。

        向量自动 L2 归一化以支持余弦相似度搜索。
        内部维护 chunk_id → FAISS id 的双向映射。

        Args:
            chunk_ids: 分块唯一 ID 列表
            texts: 分块原始文本列表（此方法中不使用，由 SQLite 管理）
            embeddings: 分块 embedding 向量列表
            metadatas: 分块元数据字典列表（此方法中不使用，由 SQLite 管理）

        Raises:
            ValueError: 输入列表长度不一致
        """
        # len()能够自动去重
        if len({len(chunk_ids), len(texts), len(embeddings), len(metadatas)}) != 1:
            raise ValueError("所有输入列表必须具有相同长度")

        if not chunk_ids:
            return

        # 转换为 numpy 并归一化
        vectors = np.array(embeddings, dtype=np.float32)
        vectors = self._normalize(vectors)

        # 分配内部 ID
        faiss_ids = []
        for chunk_id in chunk_ids:
            if chunk_id in self._reverse_id_map:
                # 已存在，使用已有索引（根据chunk_i）（更新场景）
                faiss_ids.append(self._reverse_id_map[chunk_id])
            else:
                fid = self._next_id
                self._next_id += 1
                self._id_map[fid] = chunk_id
                self._reverse_id_map[chunk_id] = fid
                faiss_ids.append(fid)

        faiss_ids_arr = np.array(faiss_ids, dtype=np.int64)

        # 添加到 FAISS 索引
        self._index.add_with_ids(vectors, faiss_ids_arr)
        self._save()

    def query(
        self,
        query_embedding: list[float],
        n_results: int = 8,
        where: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        根据查询向量执行相似度搜索。

        注意：FAISS 不支持元数据过滤，where 参数被忽略。
        如需过滤，在返回结果后由调用方自行筛选。

        Args:
            query_embedding: 查询文本的 embedding 向量
            n_results: 返回的最相似结果数量
            where: 元数据过滤条件（当前不支持，预留接口兼容性）

        Returns:
            查询结果字典，兼容原 ChromaDB 返回格式:
            {
                "ids": [[id1, id2, ...]],
                "documents": [[text1, text2, ...]],
                "metadatas": [[meta1, meta2, ...]],
                "distances": [[dist1, dist2, ...]]
            }
        """
        # 当前索引中已经存储的向量总数
        if self._index.ntotal == 0:
            return {
                "ids": [[]],
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
            }

        vector = np.array([query_embedding], dtype=np.float32)
        vector = self._normalize(vector)

        k = min(n_results, self._index.ntotal)
        # distances, indices 都是2维数组，所以下面只取第一个元素
        distances, indices = self._index.search(vector, k)

        # 将 FAISS 内部 ID 转换回 chunk_id
        chunk_ids = []
        chunk_distances = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx >= 0 and idx in self._id_map:
                chunk_ids.append(self._id_map[idx])
                chunk_distances.append(float(dist))

        return {
            "ids": [chunk_ids],
            "documents": [[]],  # 由调用方从 SQLite 填充
            "metadatas": [[]],  # 由调用方从 SQLite 填充
            "distances": [chunk_distances],
        }

    def get_chunk(self, chunk_id: str) -> Optional[dict[str, Any]]:
        """
        根据分块 ID 从元数据存储获取分块信息。

        注意：此方法需要配合 SQLite 使用，从 chunks 表查询元数据。
        仅返回向量存储层面的基本信息。

        Args:
            chunk_id: 分块唯一 ID

        Returns:
            分块数据字典（包含 FAISS 内部 ID），不存在返回 None
        """
        if chunk_id not in self._reverse_id_map:
            return None
        faiss_id = self._reverse_id_map[chunk_id]
        return {
            "id": chunk_id,
            "faiss_id": faiss_id,
            "text": None,    # 由调用方从 SQLite 填充
            "metadata": {},   # 由调用方从 SQLite 填充
        }

    def get_neighboring_chunks(
        self, document_id: str, chunk_index: int, count: int = 1
    ) -> list[dict[str, Any]]:
        """
        获取同一文档中的相邻分块（上下文）。

        注意：此功能依赖 SQLite chunks 表实现，此处仅保留接口。
        FAISS 本身不存储 document_id 元数据。

        Args:
            document_id: 文档 ID
            chunk_index: 当前分块索引
            count: 前后各取几个分块

        Returns:
            空列表 - 需要由调用方从 SQLite chunks 表查询
        """
        return []

    def delete_document(self, document_id: str) -> int:
        """
        删除指定文档的所有分块向量。

        通过遍历 ID 映射找到属于该文档的所有分块并移除。
        由于 FAISS IndexIDMap 不支持直接删除单个向量，
        此处标记删除（从 ID map 中移除），实际索引重建在下一次
        add 时触发。

        Args:
            document_id: 要删除的文档 ID (chunk_id 前缀或完整 ID)

        Returns:
            删除的分块数量
        """
        ids_to_remove = []
        for faiss_id, chunk_id in list(self._id_map.items()):
            # chunk_id 包含 document_id 相关前缀的情况
            if document_id in chunk_id:
                ids_to_remove.append((faiss_id, chunk_id))

        for faiss_id, chunk_id in ids_to_remove:
            del self._id_map[faiss_id]
            del self._reverse_id_map[chunk_id]

        if ids_to_remove:
            self._rebuild_index()
            self._save()

        return len(ids_to_remove)

    def _rebuild_index(self) -> None:
        """
        重建 FAISS 索引（移除已删除的向量）。

        由于 FAISS IndexIDMap 不支持直接删除，
        需要通过重建索引来移除标记删除的条目。
        这会从旧索引中提取保留的向量，创建新索引。
        """
        if not self._id_map:
            self._create_new()
            self._next_id = 0
            self._save()
            return

        # 重建: 从旧索引提取保留的向量
        old_index = self._index
        new_index = faiss.IndexIDMap(faiss.IndexFlatIP(self.dim))

        # 保留映射中的 ID
        keep_ids = sorted(self._id_map.keys())
        if keep_ids:
            # 逐个重建（IndexIDMap 没有 extract_vectors 方法）
            for fid in keep_ids:
                try:
                    # 使用 reconstruct 获取单个向量
                    vec = old_index.reconstruct(fid)
                    new_index.add_with_ids(np.array([vec], dtype=np.float32), np.array([fid], dtype=np.int64))
                except RuntimeError:
                    # 向量不存在于旧索引中，跳过
                    del self._id_map[fid]
                    # 同时清理反向映射
                    chunk_id = self._reverse_id_map.get(fid, "")
                    if chunk_id:
                        del self._reverse_id_map[chunk_id]

        self._index = new_index

    def count(self) -> int:
        """返回向量存储中的分块总数。"""
        return self._index.ntotal


# 单例实例
vector_store = VectorStore()
