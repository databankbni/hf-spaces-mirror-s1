/**
 * 消息相关类型定义模块
 *
 * 定义消息(Message)相关的TypeScript类型。
 */

import { SenderType, ContentType } from './common';

/**
 * 消息信息
 *
 * 记录群聊讨论中的每条消息。
 */
export interface Message {
  /** 消息ID */
  id: string;
  /** 所属讨论链ID */
  chain_id: string;
  /** 发送者ID */
  sender_id: string;
  /** 发送者类型 */
  sender_type: SenderType;
  /** 发送者显示名称 */
  sender_name: string;
  /** 消息内容 */
  content: string;
  /** 内容类型 */
  content_type: ContentType;
  /** 元数据 */
  metadata?: Record<string, unknown>;
  /** 创建时间 */
  created_at: string;
}

/**
 * 群聊发送消息响应
 */
export interface ChatResponse {
  user_message: Message;
  agent_message: Message;
}

/**
 * 流式发送消息 (POST /chat/stream) 的返回结果
 *
 * 后端立即返回 session 元信息, 后续事件通过 WebSocket 推送。
 */
export interface ChatStreamResult {
  /** chain ID */
  chain_id: string;
  /** agent 占位 packet ID (后续 done 事件的 packet_id 对应此值) */
  packet_id: string;
  /** chain 类型 (group / task) */
  chain_type: string;
  /** 父 chain ID (任务链的父链) */
  parent_chain_id: string | null;
  /** 响应 agent ID */
  agent_id: string;
  /** 响应 agent 名称 */
  agent_name: string;
  /** 用户消息 (序列化 packet) */
  user_message?: Message;
  /** no_agent 场景: 群聊中没有 agent */
  no_agent?: boolean;
  /** 错误信息 */
  error?: string;
}

/**
 * 恢复流 (POST /chat/stream/attach) 的返回结果
 *
 * 有活跃流时返回当前快照, 前端通过 WebSocket 接收后续事件;
 * 无活跃流时返回 {active: false}, 前端从 DB 渲染。
 */
export interface ChatStreamAttachResult {
  /** 是否有活跃流 */
  active: boolean;
  /** 群聊ID */
  group_id?: string;
  /** chain ID */
  chain_id?: string;
  /** packet ID */
  packet_id?: string;
  /** 已累计的 content (snapshot) */
  content?: string;
  /** 已累计的 metadata (snapshot) */
  metadata?: Record<string, unknown>;
  /** 是否正在流式 */
  is_streaming?: boolean;
  /** 是否已取消 */
  is_cancelled?: boolean;
  /** chain_start 数据 (供前端重建 reply view) */
  chain_start?: ChainStartData;
}

/**
 * 发送消息请求参数
 */
export interface SendMessageRequest {
  /** 消息内容 */
  content: string;
  /** 内容类型 */
  content_type?: ContentType;
}

/**
 * 停止Agent请求参数
 */
export interface StopAgentRequest {
  /** 停止模式 */
  mode: 'wait_complete' | 'wait_task' | 'force';
}

/**
 * WebSocket消息类型
 *
 * 包含两类:
 *   - 客户端→服务端: send_message / stop_agent / resume
 *   - 服务端→客户端:
 *     . 群聊事件: agent_message / agent_typing / system_message / task_update
 *     . 流式事件 (v2: 原 SSE 事件迁移到 WebSocket): user_message / chain_start /
 *       token / tool_call / tool_result / render_spec / chain_end / done
 *     . 错误: error
 */
export type WsNodeType =
  | 'send_message'
  | 'stop_agent'
  | 'resume'
  | 'ping'
  | 'agent_message'
  | 'agent_typing'
  | 'system_message'
  | 'task_update'
  | 'user_message'
  | 'chain_start'
  | 'token'
  | 'tool_call'
  | 'tool_result'
  | 'chain_end'
  | 'done'
  | 'error'
  | 'pong';

/**
 * WebSocket客户端消息
 */
export interface WsClientMessage {
  /** 消息类型 */
  type: WsNodeType;
  /** 消息负载 */
  payload: unknown;
}

/**
 * WebSocket服务器消息
 */
export interface WsServerMessage {
  /** 消息类型 */
  type: WsNodeType;
  /** 消息负载 */
  payload: unknown;
}

/**
 * Agent正在输入消息
 */
export interface AgentTypingPayload {
  /** Agent ID */
  agent_id: string;
  /** Agent名称 */
  agent_name: string;
}

/**
 * 系统消息负载
 */
export interface SystemMessagePayload {
  /** 消息内容 */
  content: string;
  /** 创建时间 */
  created_at: string;
}

/**
 * 任务更新负载
 */
export interface TaskUpdatePayload {
  /** 任务ID */
  task_id: string;
  /** 新状态 */
  status: string;
  /** 交付物ID（可选） */
  deliverable_id?: string;
}

/**
 * 错误负载
 */
export interface ErrorPayload {
  /** 错误代码 */
  code: string;
  /** 错误消息 */
  message: string;
}

/**
 * chain_start 事件数据 (WS payload)
 */
export interface ChainStartData {
  chain_id: string;
  chain_type: string;
  parent_chain_id: string | null;
  agent_id: string | null;
  agent_name: string | null;
}

/**
 * chain_end 事件数据 (WS payload)
 */
export interface ChainEndData {
  chain_id: string;
  status: string;
}

/**
 * token 事件 payload (WS)
 */
export interface TokenPayload {
  chain_id: string;
  sender_id: string;
  content: string;
}

/**
 * tool_call 事件 payload (WS)
 */
export interface ToolCallPayload {
  tool_name: string;
  arguments: Record<string, unknown>;
  tool_call_id?: string;
  timestamp?: string;
}

/**
 * tool_result 事件 payload (WS)
 */
export interface ToolResultPayload {
  tool_name: string;
  tool_call_id?: string;
  result: unknown;
  render_spec?: unknown;
  inject_js?: string;
  inject_description?: string;
}

/**
 * done 事件 payload (WS)
 */
export interface DonePayload {
  chain_id: string;
  packet_id: string;
  content: string;
  metadata: Record<string, unknown>;
  rollover?: unknown;
}

/**
 * error 事件 payload (WS)
 *
 * 两种形式:
 *   - chat_service fatal error: { message: string }
 *   - StreamPushPlugin tool error: { chain_id: string, content: string }
 */
export interface StreamErrorPayload {
  message?: string;
  chain_id?: string;
  content?: string;
}
