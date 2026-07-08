/**
 * Personal RAG - 应用根组件
 *
 * 三栏布局：左侧导航 | 中心内容区 | 右侧引用面板
 */

import { AppShell } from './components/layout/AppShell';
import { ChatContainer } from './components/chat/ChatContainer';
import { EmptyChat } from './components/chat/EmptyChat';
import { DocumentUploader } from './components/documents/DocumentUploader';
import { DocumentList } from './components/documents/DocumentList';
import { CitationSidebar } from './components/citations/CitationSidebar';
import { SettingsModal } from './components/settings/SettingsModal';
import { useChatStore } from './store/chatStore';
import { useSettingsStore } from './store/settingsStore';

function App() {
  const messages = useChatStore((s) => s.messages);
  const isSettingsOpen = useSettingsStore((s) => s.isSettingsOpen);

  return (
    <div className="h-screen flex flex-col bg-white dark:bg-gray-900">
      <AppShell>
        {/* 左侧导航 - 文档管理 */}
        <div className="flex flex-col gap-4 p-4">
          <DocumentUploader />
          <DocumentList />
        </div>

        {/* 中心内容 - 聊天 */}
        <div className="flex flex-col h-full">
          {messages.length === 0 ? <EmptyChat /> : <ChatContainer />}
        </div>

        {/* 右侧面板 - 引用来源 */}
        <CitationSidebar />
      </AppShell>

      {/* 设置弹窗 */}
      {isSettingsOpen && <SettingsModal />}
    </div>
  );
}

export default App;
