/**
 * 消息列表组件
 *
 * 纵向滚动显示所有对话消息。
 * 流式生成时显示实时文本和引用标记。
 */

import { useEffect, useRef } from 'react';
import { MessageBubble } from './MessageBubble';
import { StreamingText } from './StreamingText';
import { useChatStore } from '../../store/chatStore';

export function MessageList() {
  const messages = useChatStore((s) => s.messages);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const streamingText = useChatStore((s) => s.streamingText);
  const bottomRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingText]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
      {messages.length === 0 && !isStreaming && (
        <div className="text-center text-gray-400 mt-20">
          开始对话吧
        </div>
      )}

      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} />
      ))}

      {/* 流式生成中的消息 */}
      {isStreaming && (
        <div className="flex gap-3">
          <div className="w-8 h-8 rounded-full bg-blue-500 flex items-center justify-center text-white text-xs shrink-0">
            AI
          </div>
          <div className="max-w-[80%] rounded-2xl px-4 py-3 bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100">
            <StreamingText text={streamingText} />
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
