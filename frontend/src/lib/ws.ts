"use client";

import useWebSocket, { ReadyState } from "react-use-websocket";
import { useEffect } from "react";

import { wsBaseUrl } from "@/lib/config";
import { useGameStore } from "@/stores/gameStore";

export { wsBaseUrl };

/**
 * 游戏会话 WS 通道：
 * - 连接建立后服务端先发 session_init（权威快照，从 DB 重建）；
 *   客户端随即以本地确认水位发送 resync_request 获取补发（含当前交互点）；
 * - 断线指数退避自动重连，重连后同样经 session_init + resync 恢复；
 * - 所有入站消息统一进入 gameStore.handleServerMessage（去重/确认/命令对账）。
 */
export function useGameChannel(sessionId: string | null) {
  const url = sessionId ? `${wsBaseUrl()}/ws/${sessionId}` : null;

  const { sendJsonMessage, lastJsonMessage, readyState } = useWebSocket(url, {
    shouldReconnect: () => true,
    reconnectAttempts: 12,
    reconnectInterval: (attempt) => Math.min(500 * 2 ** attempt, 15000),
  });

  useEffect(() => {
    useGameStore.getState().setSender(sendJsonMessage);
  }, [sendJsonMessage]);

  useEffect(() => {
    const store = useGameStore.getState();
    if (readyState === ReadyState.OPEN) store.setConnection("connected");
    else if (readyState === ReadyState.CONNECTING || readyState === ReadyState.UNINSTANTIATED)
      store.setConnection("connecting");
    else store.setConnection("reconnecting");
  }, [readyState]);

  useEffect(() => {
    if (lastJsonMessage != null) {
      useGameStore.getState().handleServerMessage(lastJsonMessage);
    }
  }, [lastJsonMessage]);
}
