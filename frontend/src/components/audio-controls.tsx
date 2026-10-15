"use client";

import { useGameStore } from "@/stores/gameStore";
import { Button } from "@/components/ui/button";

/**
 * 音频控制（#63 / ADR-0005 §11）：静音开关 + 打断。
 *
 * 「打断」是 barge-in 的客户端一半：停播本地全部音轨，并把 `cancel_audio` 发给
 * 服务端。它**不**打断命令——命令串行、事件同事务持久化是引擎的地基，服务端在
 * 生成中本就收不到新命令。
 *
 * 语音输入（#64）与它是并列的输入通道，键盘输入永远是兜底：这里的任何失败都
 * 不影响用键盘推进剧情。
 */
export function AudioControls() {
  const muted = useGameStore((s) => s.audioMuted);
  const setMuted = useGameStore((s) => s.setAudioMuted);
  const bargeIn = useGameStore((s) => s.bargeIn);

  return (
    <div className="flex items-center gap-2">
      <Button
        tone="outline"
        size="xs"
        onClick={() => setMuted(!muted)}
        aria-pressed={muted}
        aria-label={muted ? "取消静音" : "静音"}
        title={muted ? "取消静音" : "静音"}
      >
        {muted ? "静音中" : "有声"}
      </Button>
      <Button
        tone="outline"
        size="xs"
        onClick={() => bargeIn()}
        aria-label="打断当前配音"
        title="停掉正在播放的配音"
      >
        打断配音
      </Button>
    </div>
  );
}
