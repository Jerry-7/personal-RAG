/**
 * 聊天容器组件
 *
 * 包含消息列表和输入框，占据中心区域全部高度。
 */

import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';

export function ChatContainer() {
  return (
    <div className="flex flex-col h-full">
      <MessageList />
      <ChatInput />
    </div>
  );
}
