"use client";

import { AnimatePresence, m } from "motion/react";

import { useAssetUrl } from "@/lib/asset-url";
import { useSpeakingSpeakers } from "@/lib/audio-session";
import { useCastRoster } from "@/lib/cast-roster";
import type { CharacterProfile } from "@/lib/contracts/types";
import { useGameStore } from "@/stores/gameStore";

const EASE = [0.2, 0.7, 0.2, 1] as const;

/**
 * 一位角色的立绘。剧本目前只生成头像、没有全身立绘，所以没有立绘的角色**不上台**：
 * 只剩一块浮在画上的名牌，比台上没有人更乱。头像圆框同样不放进场景。
 */
function Figure({
  name,
  profile,
  active,
  someoneActive,
  isPlayer,
  speaking,
}: {
  name: string;
  profile: CharacterProfile | undefined;
  active: boolean;
  someoneActive: boolean;
  isPlayer: boolean;
  speaking: boolean;
}) {
  const { url: fullbodyUrl } = useAssetUrl(profile?.fullbody_asset);
  const lit = active || !someoneActive;
  // 没有全身立绘就不上台：只剩一块浮在画上的名牌，比没有人还乱
  if (!fullbodyUrl) return null;

  // 你演的角色用朱砂，其他人用泥金；说话的人脚下再亮一圈青碧地光
  const tone = isPlayer
    ? { border: "border-flag/55", text: "text-flag", aura: "bg-flag/25" }
    : { border: "border-glow-gold/45", text: "text-glow-gold", aura: "bg-glow-gold/20" };

  return (
    <m.figure
      layout
      initial={{ opacity: 0, y: 28, filter: "blur(10px)" }}
      animate={{
        opacity: lit ? 1 : 0.42,
        y: active ? 0 : 10,
        scale: active ? 1.04 : 0.96,
        filter: lit ? "blur(0px)" : "blur(1.5px)",
      }}
      exit={{ opacity: 0, y: 18, filter: "blur(10px)" }}
      transition={{ duration: 0.55, ease: EASE }}
      className="relative flex h-full max-w-[34%] min-w-0 flex-1 basis-0 flex-col items-center justify-end"
    >
      {/* 背后的一团光晕 */}
      <span
        className={`absolute bottom-[12%] left-1/2 h-1/2 w-[70%] -translate-x-1/2 rounded-full blur-3xl transition-opacity duration-500 ${tone.aura} ${
          lit ? "opacity-100" : "opacity-30"
        }`}
      />

      {/* 预签名 URL 短时效、含凭证参数，仅当前视图使用 */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={fullbodyUrl}
        alt=""
        className="relative max-h-full w-auto max-w-full object-contain drop-shadow-[0_14px_30px_rgba(0,0,0,0.65)]"
      />

      {/* 名牌压在立绘脚边：有图时名字不在图上，补一块 */}
      <span
        className={`relative -mt-6 mb-[6%] rounded-full border bg-glass px-3 py-0.5 font-serif text-sm backdrop-blur-md ${tone.border} ${tone.text}`}
      >
        {name}
      </span>

      {/* 地光与声纹：说话的人脚下亮一圈；配音在放时再向外扩两圈 */}
      <span
        className={`absolute bottom-[3%] left-1/2 h-5 w-[62%] -translate-x-1/2 rounded-[50%] bg-glow-jade/30 blur-md transition-opacity duration-500 ${
          active ? "opacity-100" : "opacity-0"
        }`}
      />
      {speaking &&
        [0, 0.65].map((delay) => (
          <span
            key={delay}
            className="animate-voice-ring absolute bottom-[3%] left-1/2 -ml-[31%] h-5 w-[62%] rounded-[50%] border border-glow-jade"
            style={{ animationDelay: `${delay}s` }}
          />
        ))}
    </m.figure>
  );
}

/**
 * 立绘层：台上最多三位角色并排站在画面下方，说话的人上前提亮，其余退暗虚化；
 * 旁白时大家一起亮着。跟着指针视差朝同方向轻挪，和背景拉开前后景。
 *
 * 纯装饰（aria-hidden）：谁在说什么由字幕与剧情回顾承担。窄屏不显示，给字幕让地方。
 *
 * 自己从 store 取「台上有谁、谁在配音」——不经过游戏页转手，流式台词每来一段
 * 只重渲这一层，不牵动顶栏与侧栏。
 */
export function StageFigures() {
  const { cast, listed } = useCastRoster();
  const speaking = useSpeakingSpeakers();
  const byName = new Map(listed.map((c) => [c.name, c]));
  const playerRole = useGameStore((s) => s.playerRole);

  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-x-0 top-14 bottom-16 z-0 hidden items-end justify-center gap-[4%] px-[8%] transition-transform duration-700 ease-out sm:flex"
      style={{
        transform:
          "translate3d(calc(var(--wj-px, 0) * 12px), calc(var(--wj-py, 0) * 6px), 0)",
      }}
    >
      <AnimatePresence mode="popLayout">
        {cast.onStage.map((name) => (
          <Figure
            key={name}
            name={name}
            profile={byName.get(name)}
            active={cast.active === name}
            someoneActive={cast.active !== null}
            isPlayer={name === playerRole}
            speaking={speaking.includes(name)}
          />
        ))}
      </AnimatePresence>
    </div>
  );
}
