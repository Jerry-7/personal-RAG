/**
 * 聊天输入框组件
 *
 * 多行文本输入 + 发送按钮。
 * 当没有已索引文档时禁用。
 */

import { useState, useRef, useCallback } from 'react';
import type { KeyboardEvent } from 'react';
import { Send } from 'lucide-react';
import { useChatStore } from '../../store/chatStore';
import { useDocumentStore } from '../../store/documentStore';
import { streamChatQuery } from '../../api/chat';

export function ChatInput() {
  const [input, setInput] = useState('');
  const [isSending, setIsSending] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const addUserMessage = useChatStore((s) => s.addUserMessage);
  const startStreaming = useChatStore((s) => s.startStreaming);
  const appendToken = useChatStore((s) => s.appendToken);
  const finishStreaming = useChatStore((s) => s.finishStreaming);
  const conversationId = useChatStore((s) => s.conversationId);
  const documents = useDocumentStore((s) => s.documents);
  const indexedCount = documents.filter((d) => d.status === 'indexed').length;

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || isSending) return;

    addUserMessage(text);
    setInput('');
    setIsSending(true);
    startStreaming();

    // 发起 SSE 流式请求
    abortRef.current = streamChatQuery(text, conversationId, {
      onToken: appendToken,
      onCitation: (_index) => {
        // CitationMark 追加由 appendToken 中的 addCitation 处理
      },
      onDone: (data) => {
        finishStreaming(data.citations, data.message_id);
        setIsSending(false);
      },
      onError: (error) => {
        console.error('Chat error:', error);
        finishStreaming([], crypto.randomUUID());
        setIsSending(false);
      },
    });
  }, [input, isSending, conversationId, addUserMessage, startStreaming, appendToken, finishStreaming]);

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleCancel = () => {
    abortRef.current?.abort();
    setIsSending(false);
  };

  return (
    <div className="border-t border-gray-200 dark:border-gray-700 p-4">
      <div className="flex items-end gap-2 max-w-3xl mx-auto">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            indexedCount === 0
              ? '请先上传文档...'
              : '输入问题，按 Enter 发送 (Shift+Enter 换行)'
          }
          disabled={indexedCount === 0}
          rows={1}
          className="flex-1 resize-none rounded-xl border border-gray-300 dark:border-gray-600 px-4 py-3 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          style={{ maxHeight: '120px' }}
        />

        {isSending ? (
          <button
            onClick={handleCancel}
            className="px-4 py-3 rounded-xl bg-red-500 text-white text-sm hover:bg-red-600 transition-colors shrink-0"
          >
            取消
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!input.trim()}
            className="p-3 rounded-xl bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50 transition-colors shrink-0"
          >
            <Send className="w-5 h-5" />
          </button>
        )}
      </div>
    </div>
  );
}
