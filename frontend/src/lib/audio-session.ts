"use client";

/**
 * 会话级音频接线（#63 / ADR-0005 §11）。
 *
 * 把 `audio-tracks.ts` 的纯缓冲与 `AudioTrackPlayer` 接成一条会话级的管道：
 * WS 的控制帧与二进制帧进来 → 缓冲 → 播放。放在模块级单例里，因为音轨是
 * **连接级**资源（与后端的 `AudioTrackChannel` 一一对应），不该挂在 React 树上
 * 跟着组件重渲染。
 *
 * 与服务端的分工：服务端只负责**送**（不混音、不缓存、不重放）；停播与打断都在
 * 这里——ADR-0005 §11 的 barge-in 是客户端行为。
 */

import {
  AudioTrackPlayer,
  appendChunk,
  finishTrack,
  startTrack,
  type PendingTrack,
} from "@/lib/audio-tracks";

class AudioSession {
  private tracks: PendingTrack[] = [];
  private readonly player = new AudioTrackPlayer();
  private muted = false;

  /** 控制帧（`audio_start` / `audio_end`）。二进制帧走 `pushBinary`。 */
  handleControl(type: string, payload: unknown): void {
    if (type === "audio_start") {
      this.tracks = startTrack(this.tracks, payload);
      return;
    }
    if (type !== "audio_end") return;
    const { ready, remaining } = finishTrack(this.tracks, payload);
    this.tracks = remaining;
    if (ready) this.player.play(ready);
  }

  /** 二进制帧：当前在途轨的音频字节。 */
  pushBinary(data: ArrayBuffer): void {
    this.tracks = appendChunk(this.tracks, data);
  }

  /** 断线/重连：在途轨属于上一条连接，一并丢弃（权威文本由事件流补）。 */
  reset(): void {
    this.tracks = [];
    this.player.stopAll();
  }

  /** barge-in：停播全部音轨，返回被停掉的 `track_id`（供上报 `cancel_audio`）。 */
  bargeIn(): string[] {
    this.tracks = [];
    return this.player.stopAll();
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    this.player.setMuted(muted);
  }

  get isMuted(): boolean {
    return this.muted;
  }

  get playingCount(): number {
    return this.player.playingCount;
  }

  get pendingCount(): number {
    return this.tracks.length;
  }

  dispose(): void {
    this.tracks = [];
    this.player.dispose();
  }
}

export const audioSession = new AudioSession();

/** 把 WS 的二进制帧统一成 `ArrayBuffer`（浏览器给 Blob，测试里可能是别的）。 */
export async function toArrayBuffer(data: unknown): Promise<ArrayBuffer | null> {
  if (data instanceof ArrayBuffer) return data;
  if (typeof Blob !== "undefined" && data instanceof Blob) {
    return await data.arrayBuffer();
  }
  if (ArrayBuffer.isView(data)) {
    const view = data as ArrayBufferView;
    return view.buffer.slice(
      view.byteOffset,
      view.byteOffset + view.byteLength
    ) as ArrayBuffer;
  }
  return null;
}
