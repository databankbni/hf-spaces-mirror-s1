/**
 * WebSocket Hook模块
 *
 * 提供WebSocket连接管理，支持实时消息推送。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { WsServerMessage, WsClientMessage } from '../types';

/**
 * WebSocket连接状态
 */
export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

/**
 * WebSocket Hook配置选项
 */
interface UseWebSocketOptions {
  /** 是否自动连接 */
  autoConnect?: boolean;
  /** 重连间隔（毫秒） */
  reconnectInterval?: number;
  /** 最大重连次数 */
  maxReconnectAttempts?: number;
  /** 心跳间隔（毫秒） */
  heartbeatInterval?: number;
  /** 连接成功回调 */
  onConnect?: () => void;
  /** 断开连接回调 */
  onDisconnect?: () => void;
  /** 收到消息回调 */
  onMessage?: (message: WsServerMessage) => void;
  /** 错误回调 */
  onError?: (error: Event) => void;
}

/**
 * WebSocket Hook返回值
 */
interface UseWebSocketReturn {
  /** 连接状态 */
  status: WebSocketStatus;
  /** 发送消息 */
  send: (message: WsClientMessage) => void;
  /** 连接 */
  connect: () => void;
  /** 断开连接 */
  disconnect: () => void;
  /** 重连 */
  reconnect: () => void;
}

/**
 * WebSocket基础URL
 * - 生产模式（同源）：自动从当前页面推断 ws/wss, 路径与 API 保持一致 (/api/v1/ws)
 * - 开发模式：使用环境变量或默认值
 *
 * 注意: 后端 ws_router 注册在 v1_router 下, 实际路径为 /api/v1/ws/groups/{group_id}
 */
function getWsBaseUrl(): string {
  if (import.meta.env.PROD) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}/api/v1/ws`;
  }
  return import.meta.env.VITE_WS_URL || 'ws://localhost:8002/api/v1/ws';
}
const WS_BASE_URL = getWsBaseUrl();

/**
 * WebSocket Hook
 *
 * @param url - WebSocket端点路径（会自动拼接到基础URL）
 * @param options - 配置选项
 * @returns WebSocket操作接口
 *
 * @example
 * ```tsx
 * const { status, send, connect, disconnect } = useWebSocket('/chat/group-1', {
 *   onMessage: (msg) => console.log('Received:', msg),
 * });
 * ```
 */
export function useWebSocket(
  url: string,
  options: UseWebSocketOptions = {}
): UseWebSocketReturn {
  const {
    autoConnect = true,
    reconnectInterval = 3000,
    maxReconnectAttempts = 5,
    heartbeatInterval = 30000,
    onConnect,
    onDisconnect,
    onMessage,
    onError,
  } = options;

  const [status, setStatus] = useState<WebSocketStatus>('disconnected');
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 保存回调的ref，避免重渲染
  const onConnectRef = useRef(onConnect);
  const onDisconnectRef = useRef(onDisconnect);
  const onMessageRef = useRef(onMessage);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onConnectRef.current = onConnect;
    onDisconnectRef.current = onDisconnect;
    onMessageRef.current = onMessage;
    onErrorRef.current = onError;
  }, [onConnect, onDisconnect, onMessage, onError]);

  /**
   * 启动心跳
   */
  const startHeartbeat = useCallback(() => {
    if (heartbeatTimerRef.current) {
      clearInterval(heartbeatTimerRef.current);
    }
    heartbeatTimerRef.current = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }));
      }
    }, heartbeatInterval);
  }, [heartbeatInterval]);

  /**
   * 停止心跳
   */
  const stopHeartbeat = useCallback(() => {
    if (heartbeatTimerRef.current) {
      clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
  }, []);

  /**
   * 连接WebSocket
   */
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    const fullUrl = `${WS_BASE_URL}${url}`;
    setStatus('connecting');

    const ws = new WebSocket(fullUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setStatus('connected');
      reconnectAttemptsRef.current = 0;
      startHeartbeat();
      onConnectRef.current?.();
    };

    ws.onclose = () => {
      setStatus('disconnected');
      stopHeartbeat();
      onDisconnectRef.current?.();

      // 自动重连
      if (reconnectAttemptsRef.current < maxReconnectAttempts) {
        reconnectTimerRef.current = setTimeout(() => {
          reconnectAttemptsRef.current++;
          connect();
        }, reconnectInterval);
      }
    };

    ws.onerror = (error) => {
      setStatus('error');
      onErrorRef.current?.(error);
    };

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data) as WsServerMessage;
        onMessageRef.current?.(message);
      } catch (error) {
        console.error('Failed to parse WebSocket message:', error);
      }
    };
  }, [url, maxReconnectAttempts, reconnectInterval, startHeartbeat, stopHeartbeat]);

  /**
   * 断开连接
   */
  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    reconnectAttemptsRef.current = maxReconnectAttempts; // 阻止自动重连
    stopHeartbeat();
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setStatus('disconnected');
  }, [maxReconnectAttempts, stopHeartbeat]);

  /**
   * 重新连接
   */
  const reconnect = useCallback(() => {
    disconnect();
    reconnectAttemptsRef.current = 0;
    connect();
  }, [connect, disconnect]);

  /**
   * 发送消息
   */
  const send = useCallback((message: WsClientMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    } else {
      console.error('WebSocket is not connected');
    }
  }, []);

  // 自动连接
  useEffect(() => {
    if (autoConnect) {
      connect();
    }
    return () => {
      disconnect();
    };
  }, [autoConnect, connect, disconnect]);

  return {
    status,
    send,
    connect,
    disconnect,
    reconnect,
  };
}

export default useWebSocket;
