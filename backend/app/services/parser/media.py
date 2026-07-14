# Personal RAG - 视频/音频解析器
"""
媒体文件解析器模块

使用 faster-whisper 对视频和音频文件进行语音转录。
输出带时间戳的文本分段，支持后续分块和引用定位。

转录结果缓存于 data/transcripts/ 目录，
避免重复转录相同文件。
"""

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from app.config import settings
from app.services.parser.base import BaseParser, ParsedDocument


class MediaParser(BaseParser):
    """
    视频/音频文件解析器。

    使用 faster-whisper 进行语音转录。
    对于视频文件，先用 ffmpeg 提取音频轨道再进行转录。
    转录结果按句子分段，每段包含 start/end 时间戳。

    Attributes:
        model_size: Whisper 模型大小 (tiny/base/small/medium/large-v3)
        compute_type: 计算精度 (int8/float16/auto)
        language: 转录语言 (None=自动检测, "zh"=中文, "en"=英文)
    """

    # 支持的媒体文件扩展名
    _SUPPORTED_EXTENSIONS = [
        "mp4", "avi", "mkv", "mov", "webm",  # 视频
        "mp3", "wav", "flac", "ogg", "m4a", "aac", "wma",  # 音频
    ]

    def __init__(
        self,
        model_size: str = "base",
        compute_type: str = "int8",
        language: Optional[str] = None,
    ) -> None:
        """
        初始化媒体解析器。

        Args:
            model_size: Whisper 模型大小
                - tiny: 最快，~39M，适合英文
                - base: 平衡，~74M，中英文均可
                - small: 较好质量，~244M
                - medium: 高质量，~769M
                - large-v3: 最高质量，~1.5GB (需 GPU)
            compute_type: 计算精度，int8 在 CPU 上最快
            language: 语言代码，None 自动检测
        """
        self.model_size = model_size
        self.compute_type = compute_type
        self.language = language
        self._model = None  # 延迟加载

    @property
    def supported_extensions(self) -> list[str]:
        """返回支持的音视频文件扩展名。"""
        return self._SUPPORTED_EXTENSIONS

    def _get_model(self):
        """延迟加载 Whisper 模型（首次使用时加载，节省内存）。"""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
                device = "cuda" if self._has_cuda() else "cpu"
                self._model = WhisperModel(
                    self.model_size,
                    device=device,
                    compute_type=self.compute_type,
                )
            except ImportError:
                raise ImportError(
                    "faster-whisper 未安装。运行: pip install faster-whisper"
                )
        return self._model

    def parse(self, file_path: str) -> ParsedDocument:
        """
        解析音视频文件，执行语音转录。

        流程：
        1. 如果是视频文件，提取音频到临时 WAV 文件
        2. 使用 faster-whisper 转录
        3. 生成带时间戳的文本分段

        Args:
            file_path: 音视频文件路径

        Returns:
            ParsedDocument:
                - text: 完整转录文本
                - segments: [{start, end, text}, ...] 带时间戳分段
                - metadata: {duration_secs, language}

        Raises:
            FileNotFoundError: 文件不存在
            RuntimeError: 转录失败
        """
        import_path = Path(file_path)
        if not import_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        ext = import_path.suffix.lower().lstrip(".")

        # ── 检查缓存 ──────────────────────────────────────
        cache_path = settings.transcript_dir / f"{import_path.stem}_transcript.json"
        if cache_path.exists():
            return self._load_from_cache(cache_path, ext)

        # ── 准备音频 ──────────────────────────────────────
        audio_path = file_path
        tmp_audio = None
        is_video = ext in {"mp4", "avi", "mkv", "mov", "webm"}

        if is_video:
            # 从视频中提取音频
            tmp_audio = self._extract_audio(file_path)
            audio_path = tmp_audio

        try:
            # ── 转录 ──────────────────────────────────────
            model = self._get_model()
            segments_result, info = model.transcribe(
                audio_path,
                language=self.language,
                beam_size=5,
                vad_filter=True,  # 过滤静音段
            )

            segments = []
            full_text_parts = []
            for seg in segments_result:
                segments.append({
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": seg.text.strip(),
                })
                full_text_parts.append(seg.text.strip())

            full_text = " ".join(full_text_parts)

            result = ParsedDocument(
                text=full_text,
                metadata={
                    "duration_secs": round(info.duration, 2),
                    "language": info.language,
                    "language_probability": info.language_probability,
                    "is_video": is_video,
                },
                segments=segments,
                file_type=ext,
            )

            # ── 缓存结果 ──────────────────────────────────
            settings.transcript_dir.mkdir(parents=True, exist_ok=True)
            cache_data = {
                "text": full_text,
                "metadata": result.metadata,
                "segments": segments,
                "file_type": ext,
            }
            cache_path.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2))

            return result

        finally:
            # 清理临时文件
            if tmp_audio and Path(tmp_audio).exists():
                Path(tmp_audio).unlink()

    def _extract_audio(self, video_path: str) -> str:
        """
        使用 ffmpeg 从视频中提取音频为 16kHz 单声道 WAV。

        Args:
            video_path: 视频文件路径

        Returns:
            临时 WAV 音频文件路径

        Raises:
            RuntimeError: ffmpeg 未安装或提取失败
        """
        # 创建临时文件
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = tmp.name
        tmp.close()

        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-i", video_path,
                    "-vn",               # 不要视频流
                    "-acodec", "pcm_s16le",  # PCM 16-bit
                    "-ar", "16000",       # 16kHz 采样率
                    "-ac", "1",           # 单声道
                    "-y",                 # 覆盖输出
                    tmp_path,
                ],
                capture_output=True,
                text=True,
                timeout=300,  # 5 分钟超时
            )
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg 提取音频失败: {result.stderr}")
            return tmp_path
        except FileNotFoundError:
            raise RuntimeError(
                "ffmpeg 未安装。视频转录需要 ffmpeg 提取音频。\n"
                "安装方法: choco install ffmpeg (Windows) 或 apt install ffmpeg (Linux)"
            )

    def _has_cuda(self) -> bool:
        """检测是否有可用的 CUDA GPU。"""
        try:
            import torch
            return torch.cuda.is_available()
        except ImportError:
            return False

    def _load_from_cache(self, cache_path: Path, file_type: str) -> ParsedDocument:
        """从缓存的转录 JSON 文件加载结果。"""
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return ParsedDocument(
            text=data["text"],
            metadata=data.get("metadata", {}),
            segments=data.get("segments", []),
            file_type=file_type,
        )
