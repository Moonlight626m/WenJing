/**
 * 音轨缓冲与播放（#63 / ADR-0005 §11）。
 *
 * 后端把每条发言合成成**一条独立音轨**（不混音），经 WS 下发：
 * `audio_start{track_id,speaker,codec,sample_rate}` → 若干**二进制帧** → `audio_end{track_id}`。
 * 本模块负责把这三段拼回可播放的音频，并交给 `<audio>` 并发播放。
 *
 * 缓冲逻辑写成**纯函数**（`startTrack` / `appendChunk` / `finishTrack`），
 * 好让"多音轨不串台、收尾不漏帧"这类判定不必起浏览器就能断言——与 `gameStore`
 * 里字幕流的处理同一套路（#61）。
 */

export interface AudioTrackPayload {
  track_id: string;
  speaker: string;
  codec: string;
  sample_rate?: number;
}

/** 在途音轨：控制帧到了、`audio_end` 还没到。 */
export interface PendingTrack {
  trackId: string;
  speaker: string;
  codec: string;
  chunks: ArrayBuffer[];
}

/** 拼装完成的音轨，可交给 `<audio>`。 */
export interface FinishedTrack {
  trackId: string;
  speaker: string;
  blob: Blob;
}

function asTrackId(payload: unknown): AudioTrackPayload | null {
  if (typeof payload !== "object" || payload === null) return null;
  const p = payload as Record<string, unknown>;
  if (typeof p.track_id !== "string" || !p.track_id) return null;
  return {
    track_id: p.track_id,
    speaker: typeof p.speaker === "string" ? p.speaker : "",
    codec: typeof p.codec === "string" && p.codec ? p.codec : "audio/mpeg",
    sample_rate: typeof p.sample_rate === "number" ? p.sample_rate : 0,
  };
}

/**
 * `audio_start`：开一条轨。
 *
 * 重复的 `track_id` **不重置**已收到的字节（重发/串线不该让已经听到的音频闪回）——
 * 与字幕流里"重复 start 不重置已流出文本"是同一条理由。
 */
export function startTrack(
  tracks: PendingTrack[],
  payload: unknown
): PendingTrack[] {
  const info = asTrackId(payload);
  if (!info) return tracks;
  if (tracks.some((t) => t.trackId === info.track_id)) return tracks;
  return [
    ...tracks,
    {
      trackId: info.track_id,
      speaker: info.speaker,
      codec: info.codec,
      chunks: [],
    },
  ];
}

/**
 * 二进制帧：归给**最近开启且尚未收尾**的那条轨。
 *
 * 二进制帧本身**不带 `track_id`**（ADR-0005 §11 的协议形状是
 * `audio_start{track_id}` → 二进制帧 → `audio_end{track_id}`），所以归属靠一条
 * 隐含不变量：**一条轨的帧在流上连续**，两条轨之间才交错。服务端由
 * `TtsSynthesizer._synthesize` 保证——它对同一条轨的 start/chunk/end 之间没有
 * `await`，三步在事件循环里是原子的（`AudioTrackChannel` 侧另有用例钉住）。
 *
 * 取"最近开启"而不是"最早开启"：协议给的是**嵌套**语义（一条轨的帧夹在它的
 * start 与 end 之间），最近开启的那条正是当前打开的那条。
 */
export function appendChunk(
  tracks: PendingTrack[],
  data: ArrayBuffer,
  trackId?: string
): PendingTrack[] {
  if (tracks.length === 0) return tracks;
  const index = trackId
    ? tracks.findIndex((t) => t.trackId === trackId)
    : tracks.length - 1;
  if (index < 0) return tracks;
  const next = tracks.slice();
  next[index] = { ...next[index], chunks: [...next[index].chunks, data] };
  return next;
}

/** `audio_end`：拼成 Blob 并移出在途表；没有 start 的 end 一律丢弃。 */
export function finishTrack(
  tracks: PendingTrack[],
  payload: unknown
): { ready: FinishedTrack | null; remaining: PendingTrack[] } {
  const info = asTrackId(payload);
  if (!info) return { ready: null, remaining: tracks };
  const found = tracks.find((t) => t.trackId === info.track_id);
  if (!found) return { ready: null, remaining: tracks };
  return {
    ready: {
      trackId: found.trackId,
      speaker: found.speaker,
      // 空音轨（provider 无产出）不该造出一个静默的 `<audio>`
      blob: new Blob(found.chunks, { type: found.codec }),
    },
    remaining: tracks.filter((t) => t.trackId !== info.track_id),
  };
}

/** 收尾时丢弃全部在途轨（断线/重连：上一条连接的音频不作数）。 */
export function dropAll(): PendingTrack[] {
  return [];
}

/**
 * 多音轨播放器：后端不混音，前端就挂多个 `<audio>` 同时放。
 *
 * 只在浏览器里用（`Audio` / `URL.createObjectURL`），所以与上面的纯函数分开——
 * 纯函数可以脱离 DOM 断言，这个类不行。
 */
export class AudioTrackPlayer {
  private readonly playing = new Map<string, HTMLAudioElement>();
  private readonly urls = new Set<string>();
  private muted = false;

  /** 播放一条已拼好的音轨；同一 `track_id` 重复到达时忽略（幂等）。 */
  play(track: FinishedTrack): void {
    if (this.playing.has(track.trackId)) return;
    if (track.blob.size === 0) return;

    const url = URL.createObjectURL(track.blob);
    this.urls.add(url);
    const audio = new Audio(url);
    audio.muted = this.muted;
    this.playing.set(track.trackId, audio);

    const done = () => this.release(track.trackId, url);
    audio.addEventListener("ended", done);
    audio.addEventListener("error", done);
    // 播放失败（自动播放策略/解码）不该把页面搞崩：音轨是增强，字幕才是权威。
    void audio.play().catch(() => this.release(track.trackId, url));
  }

  /** barge-in：停播并放掉**全部**在途音轨（ADR-0005 §11 的客户端一半）。 */
  stopAll(): string[] {
    const ids = [...this.playing.keys()];
    for (const [trackId, audio] of this.playing) {
      audio.pause();
      audio.src = "";
      this.playing.delete(trackId);
    }
    this.revokeAll();
    return ids;
  }

  /** 停播指定音轨；返回是否确实停了一条（用于决定要不要发 `cancel_audio`）。 */
  stop(trackId: string): boolean {
    const audio = this.playing.get(trackId);
    if (!audio) return false;
    audio.pause();
    audio.src = "";
    this.playing.delete(trackId);
    return true;
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
    for (const audio of this.playing.values()) audio.muted = muted;
  }

  get playingCount(): number {
    return this.playing.size;
  }

  dispose(): void {
    this.stopAll();
  }

  private release(trackId: string, url: string): void {
    this.playing.delete(trackId);
    URL.revokeObjectURL(url);
    this.urls.delete(url);
  }

  private revokeAll(): void {
    for (const url of this.urls) URL.revokeObjectURL(url);
    this.urls.clear();
  }
}
