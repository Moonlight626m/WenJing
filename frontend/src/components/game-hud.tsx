"use client";

import Link from "next/link";

import type { StageValue } from "@/lib/contracts/types";
import { stageLabel } from "@/lib/labels";
import type { Connection, PendingCommand } from "@/stores/gameStore";
import { useEffectsLevel, useUiStore } from "@/stores/uiStore";
import { AudioControls } from "@/components/audio-controls";
import { Thinking } from "@/components/thinking";
import { buttonClass, iconButtonClass } from "@/components/ui/button";
import { ScrollIcon, SparkleIcon } from "@/components/ui/icons";
import { Tag } from "@/components/ui/tag";

/** 连接状态：一枚色点 + 短语，比单靠文字颜色更易在背景图上辨认。 */
const CONNECTION_LABELS: Record<string, { text: string; dot: string }> = {
  idle: { text: "未连接", dot: "bg-ink-faint" },
  connecting: { text: "连接中…", dot: "bg-warn" },
  connected: { text: "已连接", dot: "bg-ok" },
  reconnecting: { text: "重连中…", dot: "bg-warn animate-pulse" },
  closed: { text: "已断开", dot: "bg-danger" },
};

/** 学生视角的四步。七个引擎阶段折叠到这四步上，见 `stepOf`。 */
const STEPS = ["选角", "还原", "续写", "结局"] as const;

/**
 * 引擎阶段 → 第几步、这一步是否已走完。
 * `stage2_complete` 停在「还原」但已走完（等学生点进入续写），`ended` 停在「结局」且走完。
 */
function stepOf(stage: StageValue): { index: number; settled: boolean } {
  switch (stage) {
    case "stage2_reenacting":
      return { index: 1, settled: false };
    case "stage2_complete":
      return { index: 1, settled: true };
    case "stage3_extending":
      return { index: 2, settled: false };
    case "ended":
      return { index: 3, settled: true };
    default:
      return { index: 0, settled: false };
  }
}

/**
 * 进度条：走完的节点是泥金实心，当前节点是青碧并向外扩光环，没到的是空心。
 * 连线按走完与否从泥金渐到青碧。窄屏放不下，退回一枚阶段标签。
 */
function StageStepper({ stage }: { stage: StageValue }) {
  const { index, settled } = stepOf(stage);

  return (
    <>
      <ol aria-label="演绎进度" className="hidden items-center lg:flex">
        {STEPS.map((label, i) => {
          const done = i < index || (i === index && settled);
          const current = i === index && !settled;
          return (
            <li
              key={label}
              aria-current={i === index ? "step" : undefined}
              className="flex items-center"
            >
              {i > 0 && (
                <span
                  aria-hidden
                  className={`mx-2 h-px w-7 ${
                    i <= index
                      ? "bg-linear-to-r from-glow-gold to-glow-jade"
                      : "bg-rule"
                  }`}
                />
              )}
              <span className="flex items-center gap-1.5">
                <span
                  aria-hidden
                  className={`size-2 shrink-0 rounded-full ${
                    current
                      ? "animate-ring-pulse bg-glow-jade"
                      : done
                        ? "bg-glow-gold shadow-[0_0_8px_var(--wj-glow-gold)]"
                        : "border border-rule-strong"
                  }`}
                />
                <span
                  className={`text-xs ${
                    current
                      ? "font-medium text-ink"
                      : done
                        ? "text-ink-soft"
                        : "text-ink-faint"
                  }`}
                >
                  {label}
                </span>
              </span>
            </li>
          );
        })}
      </ol>
      <span className="lg:hidden">
        <Tag>{stageLabel(stage)}</Tag>
      </span>
    </>
  );
}

/**
 * 特效档位开关：亮着是「完整」，按下去切到「简洁」。系统开了「减少动态效果」时
 * 档位被锁在简洁，按钮置灰并说明原因。
 */
function EffectsToggle() {
  const level = useEffectsLevel();
  const chosen = useUiStore((s) => s.effects);
  const setEffects = useUiStore((s) => s.setEffects);
  // 用户选的是 full、实际却是 lite，只可能是系统减少动态效果压下来的
  const locked = chosen === "full" && level === "lite";
  const lite = level === "lite";

  return (
    <button
      type="button"
      onClick={() => setEffects(lite ? "full" : "lite")}
      disabled={locked}
      aria-pressed={lite}
      aria-label="简洁特效"
      title={
        locked
          ? "系统开启了「减少动态效果」，舞台特效已自动精简"
          : lite
            ? "特效：简洁（点一下打开粒子、视差与转场）"
            : "特效：完整（电脑卡顿时点一下切到简洁）"
      }
      className={iconButtonClass(lite)}
    >
      <SparkleIcon />
    </button>
  );
}

/**
 * 游玩页顶栏：悬在画面上的一条毛玻璃，左边是品牌、剧本名、进度和你演的角色，
 * 右边是推进状态、连接、特效与音频开关、剧情回顾与返回。游戏页与 /showcase 共用这一份。
 */
export function GameHud({
  sessionId,
  stage,
  scriptTitle,
  playerRole,
  connection,
  pending,
  transcriptOpen,
  onToggleTranscript,
}: {
  sessionId: string;
  stage: StageValue;
  scriptTitle: string | null;
  playerRole: string | null;
  connection: Connection;
  pending: PendingCommand | null;
  /** 不传则不显示剧情回顾开关（如画廊里单独摆的顶栏） */
  transcriptOpen?: boolean;
  onToggleTranscript?: () => void;
}) {
  const conn = CONNECTION_LABELS[connection] ?? CONNECTION_LABELS.idle;

  return (
    <header className="glass relative mx-3 mt-3 flex flex-wrap items-center justify-between gap-x-5 gap-y-2 rounded-3xl px-4 py-2 md:mx-4 md:mt-4">
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="text-sheen font-serif text-xl font-semibold tracking-[0.2em]">
          文境
        </span>
        {scriptTitle && (
          <span className="max-w-[14em] truncate font-serif text-sm text-ink-soft">
            《{scriptTitle}》
          </span>
        )}
        <StageStepper stage={stage} />
        {playerRole && (
          <span className="flex items-center gap-1.5 rounded-full border border-flag/40 bg-flag-wash px-2.5 py-0.5 text-xs font-medium text-flag">
            <span
              aria-hidden
              className="size-1.5 rounded-full bg-flag shadow-[0_0_8px_var(--wj-flag)]"
            />
            扮演：{playerRole}
          </span>
        )}
      </div>

      <div className="flex items-center gap-3 text-xs text-ink-soft">
        {pending && <Thinking label={`正在推进 ${pending.label}`} />}
        <span className="flex items-center gap-1.5" title={`会话 ${sessionId}`}>
          <span
            aria-hidden
            className={`size-1.5 shrink-0 rounded-full ${conn.dot}`}
          />
          {conn.text}
        </span>
        <div className="flex items-center gap-1.5">
          <EffectsToggle />
          <AudioControls />
          {onToggleTranscript && (
            <button
              type="button"
              onClick={onToggleTranscript}
              aria-pressed={transcriptOpen}
              aria-label="剧情回顾"
              title={transcriptOpen ? "收起剧情回顾" : "打开剧情回顾"}
              className={iconButtonClass(!transcriptOpen)}
            >
              <ScrollIcon />
            </button>
          )}
        </div>
        <Link href="/" className={buttonClass("quiet", "xs")}>
          返回首页
        </Link>
      </div>
    </header>
  );
}
