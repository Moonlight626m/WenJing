/**
 * 流式字幕（#60/#61）端到端。
 *
 * 覆盖 ADR-0005 §10 在前端一侧的三条规则：`stream_*` 是**瞬态**消息（无 seq、不进
 * 消息流、不推确认水位）；多角色并发生成时各走各的 `stream_id`，互不串台；
 * 持久 `character_speech` 一到就丢弃对应流缓冲（终态规则，收束无残留）。
 *
 * 前置：无（纯函数断言，不起浏览器/服务端）。断言的是 store 里那两段判定的纯函数
 * 入口，避免为几条消息拉起整个游玩页。
 */
import { expect, test } from "@playwright/test";

import type { WireMessage } from "../../src/stores/gameStore";
import {
  applyStreamMessage,
  settleStreams,
  type LiveStream,
} from "../../src/stores/gameStore";

function msg(
  type: string,
  payload: Record<string, unknown>
): WireMessage {
  return { type, payload };
}

function fold(messages: WireMessage[]): LiveStream[] {
  return messages.reduce<LiveStream[]>(
    (streams, message) => applyStreamMessage(streams, message) ?? streams,
    []
  );
}

test.describe("#61 流式字幕", () => {
  test("start → delta → end 拼出完整文本，且不携带 seq", () => {
    const streams = fold([
      msg("stream_start", { stream_id: "s1", speaker: "母亲" }),
      msg("stream_delta", { stream_id: "s1", text: "路上" }),
      msg("stream_delta", { stream_id: "s1", text: "小心。" }),
      msg("stream_end", { stream_id: "s1" }),
    ]);

    expect(streams).toEqual([
      { streamId: "s1", speaker: "母亲", text: "路上小心。", ended: true },
    ]);
  });

  test("首段 delta 到达即为可渲染文本（TTFT 只等首 token，不等整段）", () => {
    const streams = fold([
      msg("stream_start", { stream_id: "s1", speaker: "母亲" }),
      msg("stream_delta", { stream_id: "s1", text: "路" }),
    ]);
    expect(streams[0].text).toBe("路");
    expect(streams[0].ended).toBe(false);
  });

  test("多角色并发：各 stream_id 独立累积，互不串台", () => {
    const streams = fold([
      msg("stream_start", { stream_id: "a", speaker: "母亲" }),
      msg("stream_start", { stream_id: "b", speaker: "我" }),
      msg("stream_delta", { stream_id: "b", text: "我" }),
      msg("stream_delta", { stream_id: "a", text: "路上" }),
      msg("stream_delta", { stream_id: "b", text: "走了" }),
      msg("stream_end", { stream_id: "a" }),
    ]);

    expect(streams.map((s) => [s.speaker, s.text, s.ended])).toEqual([
      ["母亲", "路上", true],
      ["我", "我走了", false],
    ]);
  });

  test("终态规则：持久发言丢弃该角色的缓冲，只丢自己的", () => {
    const streams: LiveStream[] = [
      { streamId: "a", speaker: "母亲", text: "路上小心", ended: true },
      { streamId: "b", speaker: "我", text: "我走了", ended: false },
    ];
    expect(settleStreams(streams, "母亲")).toEqual([streams[1]]);
    expect(settleStreams(streams, null)).toEqual(streams);
    expect(settleStreams([], "母亲")).toEqual([]);
  });

  test("没有 start 的 delta / end 一律丢弃（不凭空造字幕）", () => {
    expect(applyStreamMessage([], msg("stream_delta", { stream_id: "x", text: "hi" }))).toBeNull();
    expect(applyStreamMessage([], msg("stream_end", { stream_id: "x" }))).toBeNull();
  });

  test("缺 stream_id 或空文本 → 不改状态", () => {
    const state = fold([msg("stream_start", { stream_id: "s1", speaker: "母亲" })]);
    expect(applyStreamMessage(state, msg("stream_delta", { text: "hi" }))).toBeNull();
    expect(applyStreamMessage(state, msg("stream_delta", { stream_id: "s1", text: "" }))).toBeNull();
    expect(applyStreamMessage(state, msg("stream_delta", { stream_id: "s1" }))).toBeNull();
  });

  test("重复的 start 不重置已经流出的文本（重发/串线不闪回）", () => {
    const streams = fold([
      msg("stream_start", { stream_id: "s1", speaker: "母亲" }),
      msg("stream_delta", { stream_id: "s1", text: "路上" }),
    ]);
    expect(applyStreamMessage(streams, msg("stream_start", { stream_id: "s1", speaker: "母亲" }))).toBeNull();
  });

  test("缺 speaker 的 start 用占位名兜底，不影响成流", () => {
    const streams = fold([
      msg("stream_start", { stream_id: "s1" }),
      msg("stream_delta", { stream_id: "s1", text: "嗯" }),
    ]);
    expect(streams[0].speaker).toBe("角色");
    expect(streams[0].text).toBe("嗯");
  });
});
