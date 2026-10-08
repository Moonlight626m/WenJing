"use client";

/**
 * 语音输入（#64 / ADR-0005 §11）。
 *
 * 交互取舍：识别结果**填进输入框**而不是直接提交。学生能先看一眼改错字——语音识别
 * 在课堂环境（多人、口音、噪声）里出错是常态，直接提交等于把误识别写进剧情。
 * 输入框本来就摆在那儿，多看一眼的成本远低于把一句话变成既成事实。
 *
 * 隐私：录音只在那一次 `POST` 里存在，服务端用完即弃；页面不预授权麦克风，
 * 不录音时不碰设备。权限被拒只是把这个按钮置灰并给出一句中文说明，
 * 键盘输入始终可用。
 */

import { useState, useSyncExternalStore } from "react";

import { formatApiError, transcribeSpeech } from "@/lib/api";
import { isRecordingSupported, useRecorder } from "@/lib/use-recorder";

const subscribeToNothing = () => () => {};

export function VoiceInput({
  sessionId,
  disabled,
  onText,
}: {
  sessionId: string | null;
  disabled: boolean;
  onText: (text: string) => void;
}) {
  const { status, error, start, stop, cancel } = useRecorder();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  // 支持与否只能在浏览器里判断（SSR 阶段没有 MediaRecorder）。用 `useSyncExternalStore`
  // 而不是 effect + setState：服务端快照固定 false、客户端取真实值，既避免了水合
  // 不一致，也不用为一个只读探测多跑一轮渲染。
  const supported = useSyncExternalStore(
    subscribeToNothing,
    isRecordingSupported,
    () => false
  );

  if (!supported) return null;

  const recording = status === "recording";
  const blocked = disabled || !sessionId;

  async function finish() {
    // 没有会话可归属就不该走到这儿（按钮在 `blocked` 时是禁用的），
    // 这里再判一次是为了让 `sessionId` 收窄成 `string`，不靠类型断言。
    if (!sessionId) return;
    const recordingResult = await stop();
    if (!recordingResult) return;
    setBusy(true);
    setNote(null);
    try {
      const result = await transcribeSpeech(
        sessionId,
        recordingResult.blob,
        recordingResult.durationMs
      );
      onText(result.text);
      setNote("已识别，请确认后发送。");
    } catch (err) {
      // 识别失败不影响键盘：只提示，输入框一直可用（#64 验收三）
      setNote(`没听清：${formatApiError(err)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        disabled={blocked || busy}
        onClick={() => (recording ? void finish() : void start())}
        aria-pressed={recording}
        aria-label={recording ? "结束录音并识别" : "按下开始录音"}
        title={recording ? "结束录音并识别" : "语音输入（会请求麦克风权限）"}
        className={`self-start rounded-lg border px-3 py-2 text-sm transition-colors disabled:opacity-50 ${
          recording
            ? "border-red-400 bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300"
            : "border-zinc-300 text-zinc-600 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
        }`}
      >
        {busy ? "识别中…" : recording ? "■ 结束并识别" : "🎤 语音输入"}
      </button>

      {(note || error) && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400" role="status">
          {error ?? note}
        </p>
      )}

      {recording && (
        <button
          type="button"
          onClick={cancel}
          className="self-start text-xs text-zinc-400 underline"
        >
          取消这次录音
        </button>
      )}
    </div>
  );
}
