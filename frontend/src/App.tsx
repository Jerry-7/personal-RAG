/**
 * Personal RAG - 应用根组件
 *
 * 三栏布局：左侧导航 | 中心内容区 | 右侧引用面板
 */

import { useEffect } from 'react';
import { AppShell } from './components/layout/AppShell';
import { ChatContainer } from './components/chat/ChatContainer';
import { CitationSidebar } from './components/citations/CitationSidebar';
import { KnowledgeSidebar } from './components/notes/KnowledgeSidebar';
import { NoteEditor } from './components/notes/NoteEditor';
import { SettingsModal } from './components/settings/SettingsModal';
import { useSettingsStore } from './store/settingsStore';
import { useSidebarStore } from './store/sidebarStore';
import { useChatStore } from './store/chatStore';
import { getConversation } from './api/chat';
import { restoreConversationRuns } from './services/runHistory';

function App() {
  const isSettingsOpen = useSettingsStore((s) => s.isSettingsOpen);
  const activeDraft = useSidebarStore((s) => s.activeDraft);

  useEffect(() => {
    const conversationId = useChatStore.getState().conversationId;
    if (!conversationId) return;

    let cancelled = false;
    useChatStore.getState().setLoadingHistory(true);
    void getConversation(conversationId)
      .then((conversation) => {
        if (!cancelled && useChatStore.getState().conversationId === conversationId) {
          useChatStore.getState().restoreConversation(conversation.id, conversation.messages);
          void restoreConversationRuns(conversation.id).catch(() => undefined);
        }
      })
      .catch(() => {
        if (!cancelled && useChatStore.getState().conversationId === conversationId) {
          useChatStore.getState().clearMessages();
        }
      });

    return () => { cancelled = true; };
  }, []);

  return (
    <div className="h-screen flex flex-col bg-white dark:bg-gray-900">
      <AppShell>
        {/* 左侧导航 - 文档管理 */}
        <KnowledgeSidebar />

        {/* 中心内容 - 聊天 */}
        <ChatContainer />

        {/* 右侧面板 - 引用来源 */}
        {activeDraft ? <NoteEditor /> : <CitationSidebar />}
      </AppShell>

      {/* 设置弹窗 */}
      {isSettingsOpen && <SettingsModal />}
    </div>
  );
}

export default App;
