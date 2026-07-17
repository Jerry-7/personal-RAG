/**
 * 聊天容器组件
 *
 * 始终显示输入框，无消息时展示引导内容。
 */

import { MessageSquare } from 'lucide-react';
import { useChatStore } from '../../store/chatStore';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';

export function ChatContainer() {
  const messages = useChatStore((s) => s.messages);

  return (
    <div className="flex flex-col h-full">
      {messages.length === 0 ? (
        /* 空状态引导 */
        <div className="flex-1 flex flex-col items-center justify-center text-gray-400 dark:text-gray-500">
          <MessageSquare className="w-16 h-16 mb-4" />
          <p className="text-lg font-medium">上传文档开始对话</p>
          <p className="text-sm mt-2">
            支持 PDF、Word、TXT、视频等多种格式
          </p>
        </div>
      ) : (
        <MessageList />
      )}
      <ChatInput />
    </div>
  );
}
