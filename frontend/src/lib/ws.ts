"use client";

import useWebSocket, { ReadyState } from "react-use-websocket";
import { useCallback } from "react";

export function useGameSocket(sessionId: string | null) {
  const url = sessionId ? `${getWsBaseUrl()}/ws?session_id=${sessionId}` : null;

  const { sendJsonMessage, lastJsonMessage, readyState } = useWebSocket(url, {
    shouldReconnect: () => true,
    reconnectAttempts: 10,
    reconnectInterval: (attempt) => Math.min(1000 * 2 ** attempt, 30000),
  });

  const send = useCallback(
    (message: unknown) => {
      if (readyState === ReadyState.OPEN) {
        sendJsonMessage(message);
      }
    },
    [readyState, sendJsonMessage]
  );

  return { send, lastJsonMessage, readyState };
}

function getWsBaseUrl(): string {
  if (typeof window === "undefined") return "";
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.hostname || "localhost";
  return `${proto}://${host}:8000`;
}
