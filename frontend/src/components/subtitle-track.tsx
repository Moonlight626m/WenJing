"use client";

import { useEffect, useRef, useState } from "react";

import type { ChatMessage } from "@/stores/gameStore";

/** 屏幕中下方字幕：角色行 + 旁白行（ADR-0005 §1）。 */
export interface SubtitleLine {
  key: string;
  kind: "narrative" | "character_speech";
  speaker: string | null;
  text: string;
  fading: boolean;
}

/** 多行上限 3 行（ADR-0005 §1 裁决 Q33）。 */
export const MAX_VISIBLE_SUBTITLES = 3;
/** 流结束后停留 2–3s 再淡出。 */
const DWELL_MS = 2500;
const FADE_MS = 600;

function toLine(message: ChatMessage): SubtitleLine {
  return {
    key: message.key,
    kind: message.kind === "character_speech" ? "character_speech" : "narrative",
    speaker: message.speaker,
    text: message.text,
    fading: false,
  };
}

function clearTimer(
  timers: Map<string, ReturnType<typeof setTimeout>>,
  key: string
) {
  const dwell = timers.get(key);
  if (dwell) {
    clearTimeout(dwell);
    timers.delete(key);
  }
  const fade = timers.get(`${key}:fade`);
  if (fade) {
    clearTimeout(fade);
    timers.delete(`${key}:fade`);
  }
}

/**
 * 把消息流编排为「最多 3 行、到达顺序堆叠、同 speaker 新句替换旧句、
 * 溢出排队、停留后淡出」的字幕队列。
 *
 * 仅消费已持久化的完整消息（真 token 流式由 M5 #61 接入）。
 */
export function useSubtitleQueue(messages: ChatMessage[]) {
  const [visible, setVisible] = useState<SubtitleLine[]>([]);
  const visibleRef = useRef<SubtitleLine[]>([]);
  const queueRef = useRef<SubtitleLine[]>([]);
  const timersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const seenRef = useRef(new Set<string>());

  function commit() {
    setVisible([...visibleRef.current]);
  }

  // 1) 新消息入队：同 speaker 替换、未满入列、满则排队。
  useEffect(() => {
    const incoming = messages.filter(
      (m) =>
        (m.kind === "narrative" || m.kind === "character_speech") &&
        !seenRef.current.has(m.key)
    );
    if (incoming.length === 0) return;

    let changed = false;
    for (const message of incoming) {
      seenRef.current.add(message.key);
      const line = toLine(message);
      const current = visibleRef.current;
      const sameIndex = line.speaker
        ? current.findIndex((l) => l.speaker === line.speaker)
        : -1;
      if (line.speaker) {
        // 排队中的同 speaker 旧句直接由新句取代，避免补位显示过时台词。
        queueRef.current = queueRef.current.filter(
          (l) => l.speaker !== line.speaker
        );
      }
      if (sameIndex >= 0) {
        clearTimer(timersRef.current, current[sameIndex].key);
        visibleRef.current = current.map((l, i) =>
          i === sameIndex ? line : l
        );
        changed = true;
      } else if (current.length < MAX_VISIBLE_SUBTITLES) {
        visibleRef.current = [...current, line];
        changed = true;
      } else {
        queueRef.current.push(line);
      }
    }
    if (changed) commit();
  }, [messages]);

  // 会话重置（消息清空）时清空字幕与计时器。
  useEffect(() => {
    if (messages.length === 0 && seenRef.current.size > 0) {
      seenRef.current.clear();
      queueRef.current = [];
      for (const timer of timersRef.current.values()) clearTimeout(timer);
      timersRef.current.clear();
      visibleRef.current = [];
      commit();
    }
  }, [messages]);

  // 2) 为可见行武装「停留 → 淡出 → 移除并补位」计时器。
  useEffect(() => {
    const keys = new Set(visible.map((l) => l.key));
    for (const [key, timer] of timersRef.current) {
      const baseKey = key.endsWith(":fade") ? key.slice(0, -5) : key;
      if (!keys.has(baseKey)) {
        clearTimeout(timer);
        timersRef.current.delete(key);
      }
    }

    for (const line of visible) {
      if (line.fading || timersRef.current.has(line.key)) continue;
      const dwellTimer = setTimeout(() => {
        visibleRef.current = visibleRef.current.map((l) =>
          l.key === line.key ? { ...l, fading: true } : l
        );
        setVisible([...visibleRef.current]);
        const fadeTimer = setTimeout(() => {
          timersRef.current.delete(line.key);
          timersRef.current.delete(`${line.key}:fade`);
          const queued = queueRef.current.shift();
          const remaining = visibleRef.current.filter(
            (l) => l.key !== line.key
          );
          visibleRef.current = queued
            ? [...remaining, { ...queued, fading: false }]
            : remaining;
          commit();
        }, FADE_MS);
        timersRef.current.set(`${line.key}:fade`, fadeTimer);
      }, DWELL_MS);
      timersRef.current.set(line.key, dwellTimer);
    }
  }, [visible]);

  // 卸载时清理全部计时器。
  useEffect(() => {
    const timers = timersRef.current;
    return () => {
      for (const timer of timers.values()) clearTimeout(timer);
      timers.clear();
    };
  }, []);

  return visible;
}

/** 底部字幕层：旁白居中斜体，角色行 `角色：台词`（无气泡）。 */
export function SubtitleTrack({ messages }: { messages: ChatMessage[] }) {
  const lines = useSubtitleQueue(messages);
  if (lines.length === 0) return null;

  return (
    <div
      className="flex w-full flex-col items-center gap-1.5"
      data-testid="subtitle-track"
    >
      {lines.map((line) =>
        line.kind === "character_speech" ? (
          <p
            key={line.key}
            data-testid="subtitle-line"
            className={`max-w-[92%] whitespace-pre-wrap break-words text-center text-base leading-relaxed text-white transition-opacity duration-500 [text-shadow:0_1px_3px_rgba(0,0,0,0.95)] md:text-xl ${
              line.fading ? "opacity-0" : "opacity-100"
            }`}
          >
            <span className="font-semibold text-amber-300">
              {line.speaker ?? "角色"}：
            </span>
            {line.text}
          </p>
        ) : (
          <p
            key={line.key}
            data-testid="subtitle-line"
            className={`max-w-[92%] whitespace-pre-wrap break-words text-center text-sm italic leading-relaxed text-white/90 transition-opacity duration-500 [text-shadow:0_1px_3px_rgba(0,0,0,0.95)] md:text-base ${
              line.fading ? "opacity-0" : "opacity-100"
            }`}
          >
            {line.text}
          </p>
        )
      )}
    </div>
  );
}
