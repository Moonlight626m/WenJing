"use client";

/**
 * 录音状态机（#64）。
 *
 * 三条产品约束直接写进这个 hook：
 *
 * - **不偷录**：`start()` 只由用户的显式操作触发，`MediaRecorder` 的构造与
 *   `getUserMedia` 都发生在那一刻——页面加载、进入游玩页都不会去碰麦克风。
 * - **权限被拒是正常路径**：`NotAllowedError` / `NotFoundError` 都映射成可读的中文
 *   提示，而不是抛一个英文 DOMException 到界面上。
 * - **失败可回退键盘**：任何失败都只是把 `error` 置上，输入框照常可用（#64 验收三）。
 */

import { useCallback, useEffect, useRef, useState } from "react";

export type RecorderStatus = "idle" | "requesting" | "recording" | "denied" | "error";

export interface Recording {
  blob: Blob;
  durationMs: number;
}

const PERMISSION_HINTS: Record<string, string> = {
  NotAllowedError: "麦克风权限被拒绝。请在浏览器地址栏的权限里允许后重试，或直接用键盘输入。",
  PermissionDeniedError: "麦克风权限被拒绝。请在浏览器权限里允许后重试，或直接用键盘输入。",
  NotFoundError: "没有找到可用的麦克风设备，请直接用键盘输入。",
  NotReadableError: "麦克风被其他程序占用，请关闭后重试，或直接用键盘输入。",
  SecurityError: "当前页面不是安全上下文（需要 HTTPS 或 localhost），无法录音。",
};

export function hintForError(err: unknown): string {
  const name = (err as { name?: string } | null)?.name ?? "";
  return PERMISSION_HINTS[name] ?? "录音失败，请改用键盘输入。";
}

/** 浏览器是否支持录音；不支持时 UI 直接不显示录音按钮，而不是点了才报错。 */
export function isRecordingSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof MediaRecorder !== "undefined" &&
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia
  );
}

export function useRecorder() {
  const [status, setStatus] = useState<RecorderStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedAtRef = useRef<number>(0);
  const streamRef = useRef<MediaStream | null>(null);

  const releaseStream = useCallback(() => {
    // 不 release 的话浏览器会一直显示"正在录音"的标签页指示
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => releaseStream, [releaseStream]);

  const start = useCallback(async () => {
    setError(null);
    if (!isRecordingSupported()) {
      setStatus("error");
      setError("当前浏览器不支持录音，请用键盘输入。");
      return;
    }
    setStatus("requesting");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (err) {
      setStatus("denied");
      setError(hintForError(err));
      return;
    }
    streamRef.current = stream;
    chunksRef.current = [];
    startedAtRef.current = Date.now();
    const recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunksRef.current.push(event.data);
    };
    recorderRef.current = recorder;
    recorder.start();
    setStatus("recording");
  }, []);

  /** 停止并返回录音；没有有效数据时返回 null。 */
  const stop = useCallback(async (): Promise<Recording | null> => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === "inactive") {
      releaseStream();
      setStatus("idle");
      return null;
    }
    const finished = new Promise<void>((resolve) => {
      recorder.onstop = () => resolve();
    });
    recorder.stop();
    await finished;
    releaseStream();
    recorderRef.current = null;
    setStatus("idle");

    const durationMs = Date.now() - startedAtRef.current;
    const blob = new Blob(chunksRef.current, {
      type: recorder.mimeType || "audio/webm",
    });
    chunksRef.current = [];
    if (blob.size === 0) {
      setError("没有录到声音，请重试或改用键盘输入。");
      return null;
    }
    return { blob, durationMs };
  }, [releaseStream]);

  const cancel = useCallback(() => {
    recorderRef.current?.stop();
    recorderRef.current = null;
    releaseStream();
    chunksRef.current = [];
    setStatus("idle");
    setError(null);
  }, [releaseStream]);

  return { status, error, start, stop, cancel, clearError: () => setError(null) };
}
