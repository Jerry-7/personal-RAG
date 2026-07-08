/**
 * 视频来源展示组件
 *
 * 显示视频播放器（跳转到引用时间戳位置）、
 * 可点击的时间戳标记和对应的转录文本。
 */

import { useRef, useEffect } from 'react';
import type { SourceResponse } from '../../types/source';
import type { CitationData } from '../../types/chat';

interface VideoCitationProps {
  source: SourceResponse;
  citation: CitationData;
}

export function VideoCitation({ source, citation }: VideoCitationProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const { chunk } = source;

  // 自动跳转到时间戳位置
  useEffect(() => {
    if (videoRef.current && chunk.start_timestamp != null) {
      videoRef.current.currentTime = chunk.start_timestamp;
    }
  }, [chunk.start_timestamp]);

  const handleTimestampClick = (time: number) => {
    if (videoRef.current) {
      videoRef.current.currentTime = time;
      videoRef.current.play();
    }
  };

  // 构建视频 URL（通过后端文件服务）
  const videoUrl = `/files/${source.document.filename}`;

  return (
    <div className="space-y-4">
      {/* 视频播放器 */}
      <div className="rounded-lg overflow-hidden bg-black">
        <video
          ref={videoRef}
          src={videoUrl}
          controls
          className="w-full"
          preload="metadata"
        >
          您的浏览器不支持视频播放
        </video>
      </div>

      {/* 时间戳标记 */}
      {chunk.start_timestamp != null && (
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => handleTimestampClick(chunk.start_timestamp!)}
            className="timestamp-marker"
          >
            ▶ {formatTime(chunk.start_timestamp!)}
            {chunk.end_timestamp != null && ` - ${formatTime(chunk.end_timestamp)}`}
          </button>

          {citation.start_timestamp != null && citation.start_timestamp !== chunk.start_timestamp && (
            <button
              onClick={() => handleTimestampClick(citation.start_timestamp!)}
              className="timestamp-marker"
            >
              ▶ {formatTime(citation.start_timestamp)}
              {citation.end_timestamp != null && ` - ${formatTime(citation.end_timestamp)}`}
            </button>
          )}
        </div>
      )}

      {/* 转录文本 */}
      <div>
        <h4 className="text-xs font-semibold text-gray-500 uppercase mb-2">转录文本</h4>
        <div className="bg-yellow-50 dark:bg-yellow-900/30 border-l-4 border-yellow-400 pl-3 py-2 rounded-r">
          <p className="text-sm text-gray-800 dark:text-gray-200 leading-relaxed whitespace-pre-wrap">
            {chunk.text}
          </p>
          {chunk.start_timestamp != null && (
            <p className="text-xs text-gray-400 mt-2">
              {formatTime(chunk.start_timestamp!)}
              {chunk.end_timestamp != null && ` - ${formatTime(chunk.end_timestamp)}`}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}
