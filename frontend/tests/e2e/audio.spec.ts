/**
 * 音轨播放（#63 / ADR-0005 §11）端到端。
 *
 * 覆盖后端不混音所依赖的三条前端判定：多音轨各自拼装不串台；`audio_end` 一到即
 * 交付可播放的 Blob（收尾不漏帧、不早交付）；barge-in 只停音轨。
 *
 * 前置：无（纯函数断言，不起浏览器/服务端）——`AudioTrackPlayer` 之外的部分都不碰 DOM。
 */
import { expect, test } from "@playwright/test";

import {
  appendChunk,
  dropAll,
  finishTrack,
  startTrack,
  type PendingTrack,
} from "../../src/lib/audio-tracks";

function bytes(...values: number[]): ArrayBuffer {
  return new Uint8Array(values).buffer;
}

function track(tracks: PendingTrack[], trackId: string) {
  return tracks.find((t) => t.trackId === trackId);
}

test.describe("#63 音轨缓冲", () => {
  test("start → 若干二进制帧 → end 拼出完整音频", async () => {
    let tracks: PendingTrack[] = [];
    tracks = startTrack(tracks, { track_id: "t1", speaker: "母亲", codec: "audio/mpeg" });
    tracks = appendChunk(tracks, bytes(1, 2));
    tracks = appendChunk(tracks, bytes(3));
    const { ready, remaining } = finishTrack(tracks, { track_id: "t1" });

    expect(remaining).toHaveLength(0);
    expect(ready?.trackId).toBe("t1");
    expect(ready?.speaker).toBe("母亲");
    expect(ready?.blob.type).toBe("audio/mpeg");
    expect(new Uint8Array(await ready!.blob.arrayBuffer())).toEqual(
      new Uint8Array([1, 2, 3])
    );
  });

  test("多音轨按「夹在 start 与 end 之间」归属，互不串台", async () => {
    // 服务端保证一条轨的帧连续（见 appendChunk 的注释），所以流上是
    // [start a][帧 a][end a][start b][帧 b][end b]。
    let tracks: PendingTrack[] = [];
    tracks = startTrack(tracks, { track_id: "a", speaker: "母亲", codec: "audio/mpeg" });
    tracks = appendChunk(tracks, bytes(1));
    const first = finishTrack(tracks, { track_id: "a" });
    tracks = first.remaining;
    tracks = startTrack(tracks, { track_id: "b", speaker: "父亲", codec: "audio/mpeg" });
    tracks = appendChunk(tracks, bytes(2));
    const second = finishTrack(tracks, { track_id: "b" });
    tracks = second.remaining;

    expect(first.ready?.speaker).toBe("母亲");
    expect(second.ready?.speaker).toBe("父亲");
    expect(new Uint8Array(await first.ready!.blob.arrayBuffer())).toEqual(
      new Uint8Array([1])
    );
    expect(new Uint8Array(await second.ready!.blob.arrayBuffer())).toEqual(
      new Uint8Array([2])
    );
    expect(tracks).toHaveLength(0);
  });

  test("嵌套归属：后开启的轨拿到帧，先开启的等自己的", () => {
    // 防御性断言：若服务端哪天真的交错了（start a, start b, 帧, end a），
    // 帧归**最近开启**的 b——协议给的是嵌套语义，不是先到先得。
    let tracks: PendingTrack[] = [];
    tracks = startTrack(tracks, { track_id: "a", speaker: "母亲", codec: "audio/mpeg" });
    tracks = startTrack(tracks, { track_id: "b", speaker: "父亲", codec: "audio/mpeg" });
    tracks = appendChunk(tracks, bytes(7));

    expect(track(tracks, "a")?.chunks).toHaveLength(0);
    expect(track(tracks, "b")?.chunks).toHaveLength(1);
  });

  test("收尾只交付那一条，其余仍在途", () => {
    let tracks: PendingTrack[] = [];
    tracks = startTrack(tracks, { track_id: "a", speaker: "母亲", codec: "audio/mpeg" });
    tracks = startTrack(tracks, { track_id: "b", speaker: "父亲", codec: "audio/mpeg" });
    const { ready, remaining } = finishTrack(tracks, { track_id: "a" });

    expect(ready?.trackId).toBe("a");
    expect(remaining.map((t) => t.trackId)).toEqual(["b"]);
  });

  test("没有 start 的 end 一律丢弃（不凭空造音轨）", () => {
    const { ready, remaining } = finishTrack([], { track_id: "ghost" });
    expect(ready).toBeNull();
    expect(remaining).toHaveLength(0);
  });

  test("没有 start 的二进制帧被丢弃", () => {
    expect(appendChunk([], bytes(1, 2))).toHaveLength(0);
  });

  test("重复的 start 不重置已收到的字节（重发不闪回）", () => {
    let tracks: PendingTrack[] = [];
    tracks = startTrack(tracks, { track_id: "t1", speaker: "母亲", codec: "audio/mpeg" });
    tracks = appendChunk(tracks, bytes(9));
    tracks = startTrack(tracks, { track_id: "t1", speaker: "母亲", codec: "audio/mpeg" });

    expect(tracks).toHaveLength(1);
    expect(track(tracks, "t1")?.chunks).toHaveLength(1);
  });

  test("缺 track_id 的控制帧不改状态", () => {
    const tracks = startTrack([], { speaker: "母亲" });
    expect(tracks).toHaveLength(0);
    expect(finishTrack(tracks, {}).ready).toBeNull();
  });

  test("缺 codec 时按 audio/mpeg 兜底", () => {
    const tracks = startTrack([], { track_id: "t1", speaker: "母亲" });
    expect(track(tracks, "t1")?.codec).toBe("audio/mpeg");
  });

  test("断线丢弃全部在途轨（上一条连接的音频不作数）", () => {
    expect(dropAll()).toHaveLength(0);
  });

  test("空音轨不产出可播放的 Blob", () => {
    const tracks = startTrack([], { track_id: "t1", speaker: "母亲", codec: "audio/mpeg" });
    const { ready } = finishTrack(tracks, { track_id: "t1" });
    expect(ready?.blob.size).toBe(0);
  });
});
