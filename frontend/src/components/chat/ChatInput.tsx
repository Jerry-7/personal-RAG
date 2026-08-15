/**
 * 聊天输入框组件
 *
 * 多行文本输入 + 发送按钮。
 * 当没有已索引文档时禁用。
 */

import { useState, useRef, useCallback } from 'react';
import type { KeyboardEvent } from 'react';
import { Send, Square } from 'lucide-react';
import type { ChatMode } from '../../types/chat';
import { useChatStore } from '../../store/chatStore';
import { useDocumentStore } from '../../store/documentStore';
import { useNoteStore } from '../../store/noteStore';
import { startChatQuery, stopChatExecution } from '../../services/chatExecution';

export function ChatInput() {
  const [input, setInput] = useState('');
  const [mode, setMode] = useState<ChatMode>('auto');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const conversationId = useChatStore((s) => s.conversationId);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const isLoadingHistory = useChatStore((s) => s.isLoadingHistory);
  const documents = useDocumentStore((s) => s.documents);
  const indexedCount = documents.filter((d) => d.status === 'indexed').length;
  const indexedNoteCount = useNoteStore((s) => s.notes.filter((note) => note.index_status === 'indexed').length);
  const hasLocalKnowledge = indexedCount + indexedNoteCount > 0;

  const handleSend = useCallback(() => {
    const text = input.trim();
    if (!text || isStreaming || isLoadingHistory) return;

    setInput('');
    startChatQuery(text, conversationId, mode);
  }, [input, isStreaming, isLoadingHistory, conversationId, mode]);

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleCancel = () => {
    void stopChatExecution();
  };

  return (
    <div className="border-t border-gray-200 dark:border-gray-700 p-4">
      <div className="mx-auto mb-2 flex max-w-3xl items-center gap-1" role="group" aria-label="研究模式">
        {(['auto', 'local', 'web'] as ChatMode[]).map((item) => (
          <button key={item} onClick={() => setMode(item)} disabled={isStreaming} className={`h-7 min-w-14 px-2 text-xs disabled:opacity-50 ${mode === item ? 'bg-gray-800 text-white dark:bg-gray-100 dark:text-gray-900' : 'border border-gray-200 text-gray-500 dark:border-gray-700'} ${item === 'auto' ? 'rounded-l' : item === 'web' ? 'rounded-r' : ''}`}>
            {{ auto: '自动', local: '本地', web: '网页' }[item]}
          </button>
        ))}
      </div>
      <div className="flex items-end gap-2 max-w-3xl mx-auto">
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            mode === 'local' && !hasLocalKnowledge
              ? '本地模式需要先上传文档或索引笔记'
              : '输入问题，按 Enter 发送'
          }
          disabled={isLoadingHistory || (mode === 'local' && !hasLocalKnowledge)}
          rows={1}
          className="flex-1 resize-none rounded-xl border border-gray-300 dark:border-gray-600 px-4 py-3 text-sm bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
          style={{ maxHeight: '120px' }}
        />

        {isStreaming ? (
          <button
            onClick={handleCancel}
            title="停止生成"
            className="p-3 rounded bg-red-600 text-white hover:bg-red-700 transition-colors shrink-0"
          >
            <Square className="h-5 w-5" />
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={!input.trim()}
            title="发送"
            className="p-3 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors shrink-0"
          >
            <Send className="w-5 h-5" />
          </button>
        )}
      </div>
    </div>
  );
}
