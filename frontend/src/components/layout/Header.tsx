/**
 * 顶部导航栏组件
 *
 * 显示应用标题、当前模型名称和设置入口。
 */

import { useEffect, useState } from 'react';
import { MessageSquarePlus, PanelLeft, Settings } from 'lucide-react';
import { useSettingsStore } from '../../store/settingsStore';
import { useLayoutStore } from '../../store/layoutStore';
import { useChatStore } from '../../store/chatStore';
import { getConversation, listConversations } from '../../api/chat';
import type { ConversationSummary } from '../../types/chat';
import { restoreConversationRuns } from '../../services/runHistory';

export function Header() {
  const openSettings = useSettingsStore((s) => s.openSettings);
  const settings = useSettingsStore((s) => s.settings);
  const toggleKnowledge = useLayoutStore((s) => s.toggleKnowledge);
  const conversationId = useChatStore((s) => s.conversationId);
  const isStreaming = useChatStore((s) => s.isStreaming);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const activeModel = settings
    ? settings.llm_provider === 'ollama'
      ? settings.ollama.llm_model
      : settings.llm_provider === 'openai'
        ? settings.openai.llm_model
        : settings.anthropic.llm_model
    : '';

  useEffect(() => {
    void listConversations().then(setConversations).catch(() => setConversations([]));
  }, [conversationId, isStreaming]);

  const handleConversationChange = async (id: string) => {
    if (!id || id === conversationId || isStreaming) return;
    const previousId = useChatStore.getState().conversationId;
    useChatStore.getState().setLoadingHistory(true);
    try {
      const conversation = await getConversation(id);
      useChatStore.getState().restoreConversation(conversation.id, conversation.messages);
      await restoreConversationRuns(conversation.id).catch(() => {
        useChatStore.getState().setRunHistory([]);
      });
    } catch {
      useChatStore.getState().setLoadingHistory(false);
      if (previousId) useChatStore.getState().setConversationId(previousId);
    }
  };

  return (
    <header className="h-14 border-b border-gray-200 dark:border-gray-700 flex items-center justify-between px-4 bg-white dark:bg-gray-900 shrink-0">
      <div className="flex items-center gap-3">
        <button onClick={toggleKnowledge} title="知识库" className="mobile-nav-toggle p-2 rounded hover:bg-gray-100 dark:hover:bg-gray-800"><PanelLeft className="h-5 w-5" /></button>
        <h1 className="header-title text-lg font-semibold text-gray-900 dark:text-white">
          Personal RAG
        </h1>
        {settings && (
          <span className="header-model text-xs text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 px-2 py-0.5 rounded-full">
            {settings.llm_provider}: {activeModel}
          </span>
        )}
      </div>

      <div className="flex min-w-0 items-center gap-2">
        <select
          aria-label="历史对话"
          title="历史对话"
          value={conversationId ?? ''}
          disabled={isStreaming}
          onChange={(event) => void handleConversationChange(event.target.value)}
          className="header-history h-8 max-w-56 rounded border border-gray-200 bg-white px-2 text-xs text-gray-600 disabled:opacity-50 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-300"
        >
          <option value="">历史对话</option>
          {conversations.map((conversation) => (
            <option key={conversation.id} value={conversation.id}>
              {conversation.title || '未命名对话'}
            </option>
          ))}
        </select>
        <button
          onClick={() => useChatStore.getState().clearMessages()}
          disabled={isStreaming}
          className="p-2 rounded-lg hover:bg-gray-100 disabled:opacity-50 dark:hover:bg-gray-800 transition-colors"
          title="新建对话"
        >
          <MessageSquarePlus className="h-5 w-5 text-gray-600 dark:text-gray-400" />
        </button>
        <button
          onClick={openSettings}
          className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          title="设置"
        >
          <Settings className="w-5 h-5 text-gray-600 dark:text-gray-400" />
        </button>
      </div>
    </header>
  );
}
