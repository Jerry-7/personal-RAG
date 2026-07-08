/**
 * 消息气泡组件
 *
 * 渲染单条用户或 AI 消息。
 * AI 消息中的 [N] 引用标记渲染为可点击的 CitationMark。
 */

import { useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CitationMark } from './CitationMark';
import type { MessageItem } from '../../types/chat';

interface MessageBubbleProps {
  message: MessageItem;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  // 将 AI 回复中的 [N] 替换为 CitationMark 占位符
  const { parts, hasCitations } = useMemo(() => {
    if (isUser || !message.citations?.length) {
      return { parts: null, hasCitations: false };
    }
    // 分割文本，将 [N] 提取为独立标记
    const regex = /\[(\d+)\]/g;
    const segments: Array<{ type: 'text' | 'citation'; content: string; index?: number }> = [];
    let lastIdx = 0;
    let match: RegExpExecArray | null;

    while ((match = regex.exec(message.content)) !== null) {
      if (match.index > lastIdx) {
        segments.push({ type: 'text', content: message.content.slice(lastIdx, match.index) });
      }
      segments.push({ type: 'citation', content: match[0], index: parseInt(match[1]) });
      lastIdx = match.index + match[0].length;
    }
    if (lastIdx < message.content.length) {
      segments.push({ type: 'text', content: message.content.slice(lastIdx) });
    }
    return { parts: segments, hasCitations: segments.some((s) => s.type === 'citation') };
  }, [message.content, message.citations, isUser]);

  return (
    <div className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* 头像 */}
      <div
        className={`w-8 h-8 rounded-full flex items-center justify-center text-white text-xs shrink-0 ${
          isUser ? 'bg-green-500' : 'bg-blue-500'
        }`}
      >
        {isUser ? 'U' : 'AI'}
      </div>

      {/* 内容 */}
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 ${
          isUser
            ? 'bg-blue-500 text-white'
            : 'bg-gray-100 dark:bg-gray-800 text-gray-900 dark:text-gray-100'
        }`}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{message.content}</p>
        ) : hasCitations && parts ? (
          <div className="text-sm leading-relaxed">
            {parts.map((part, i) =>
              part.type === 'citation' ? (
                <CitationMark
                  key={i}
                  index={part.index!}
                  citation={message.citations.find((c) => c.index === part.index)}
                />
              ) : (
                <span key={i}>
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      p: ({ children }) => <span>{children}</span>,
                    }}
                  >
                    {part.content}
                  </ReactMarkdown>
                </span>
              )
            )}
          </div>
        ) : (
          <div className="text-sm leading-relaxed prose prose-sm dark:prose-invert max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}
