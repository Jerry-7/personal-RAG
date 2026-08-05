/**
 * 聊天容器组件
 *
 * 始终显示输入框，无消息时展示引导内容。
 */

import { LoaderCircle, MessageSquare } from 'lucide-react';
import { useChatStore } from '../../store/chatStore';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';

export function ChatContainer() {
  const messages = useChatStore((s) => s.messages);
  const isLoadingHistory = useChatStore((s) => s.isLoadingHistory);

  return (
    <div className="flex flex-col h-full">
      {isLoadingHistory ? (
        <div className="flex flex-1 items-center justify-center text-gray-400">
          <LoaderCircle className="h-6 w-6 animate-spin" aria-label="正在加载对话" />
        </div>
      ) : messages.length === 0 ? (
        /* 空状态引导 */
        <div className="flex-1 flex flex-col items-center justify-center text-gray-400 dark:text-gray-500">
          <MessageSquare className="w-16 h-16 mb-4" />
          <p className="text-lg font-medium">开始你的研究</p>
          <p className="text-sm mt-2">
            可以使用本地文档、笔记或网页来源
          </p>
        </div>
      ) : (
        <MessageList />
      )}
      <ChatInput />
    </div>
  );
}
