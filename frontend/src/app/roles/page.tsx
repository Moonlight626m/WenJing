"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AnimatePresence } from "motion/react";

import { ApiError, getScriptDetail, getStatus, submitAsyncCommandRest } from "@/lib/api";
import { buildCommand } from "@/lib/session-cache";
import { useGameStore } from "@/stores/gameStore";
import { useEffectsLevel, useUiStore } from "@/stores/uiStore";
import { GameStage } from "@/components/game-stage";
import { FirstActWaiting, RoleCard } from "@/components/role-card";
import { ToastHost } from "@/components/toast-host";
import { buttonClass } from "@/components/ui/button";
import { MotionRoot } from "@/components/ui/motion-root";
import { Empty, Loading } from "@/components/ui/states";
import { PageShell } from "@/components/ui/section";
import { Tag } from "@/components/ui/tag";
import type { CharacterProfile, PlayerCommand } from "@/lib/contracts/types";

function RolesContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const sessionId = searchParams.get("id");
  const scriptParam = searchParams.get("script");
  const scriptId = scriptParam && /^\d+$/.test(scriptParam) ? scriptParam : null;

  const push = useUiStore((s) => s.push);
  const storeCharacters = useGameStore((s) => s.characters);
  const storeTitle = useGameStore((s) => s.scriptTitle);
  const setScriptInfo = useGameStore((s) => s.setScriptInfo);
  const hydrateEffects = useUiStore((s) => s.hydrateEffects);
  const effects = useEffectsLevel();

  const [playableRoles, setPlayableRoles] = useState<string[]>([]);
  const [selectedRole, setSelectedRole] = useState<string | null>(null);
  // 在等首幕：记下选的角色与起始时间，等待过场据此显示角色名和已等秒数
  const [waiting, setWaiting] = useState<{ role: string; since: number } | null>(null);
  const submitting = waiting !== null;
  // 超时/失败后的重试复用同一 command_id：服务端可能已经跑完并落库，命令表的幂等
  // 闸据此返回首次结果，而不是再跑一轮（选角后立刻重跑会多推一个 beat）。
  const pending = useRef<{ role: string; command: PlayerCommand } | null>(null);

  useEffect(() => {
    hydrateEffects();
  }, [hydrateEffects]);

  useEffect(() => {
    if (!sessionId) return;
    getStatus(sessionId)
      .then((status) => {
        if (status.stage === "init" || status.stage === "stage1_creating") {
          // 旧匿名导入流程已移除，无法推进的会话回落学生空间。
          push({ kind: "error", title: "该会话缺少剧本，请从剧本广场重新开局" });
          router.replace("/student");
          return;
        }
        setPlayableRoles(status.playable_roles);
        setSelectedRole(status.selected_role);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          push({ kind: "error", title: "会话不存在，请重新创建" });
          router.replace("/");
        }
      });
  }, [sessionId, push, router]);

  // 角色简介只在开局时的内存 store 中；刷新后丢失，从剧本详情重建。
  useEffect(() => {
    if (storeCharacters.length > 0 || !scriptId) return;
    getScriptDetail(Number(scriptId))
      .then((detail) => {
        if (detail.package) setScriptInfo(detail.package);
      })
      .catch(() => {
        // 拿不到剧本包时退化为仅角色名，不阻塞选角。
      });
  }, [scriptId, storeCharacters.length, setScriptInfo]);

  const characters: CharacterProfile[] =
    storeCharacters.length > 0
      ? storeCharacters
      : playableRoles.map((name) => ({
          name,
          public_background: "（刷新后简介不可用，仅列角色名）",
          personality_traits: [],
          speech_style: null,
          knowledge_boundary: { knows: [], not_knows: [] },
          is_player_playable: { value: true, reason: "" },
        }));

  async function handleSelect(role: string) {
    if (!sessionId || submitting) return;
    setWaiting({ role, since: Date.now() });
    // 换了角色就换命令；同一角色重试沿用旧 command_id（见 pending 的注释）
    if (pending.current?.role !== role) {
      pending.current = {
        role,
        command: buildCommand(sessionId, "select_role", { role_name: role }),
      };
    }
    const command = pending.current.command;
    try {
      const receipt = await submitAsyncCommandRest(sessionId, command);
      if (receipt.async_state === "failed") {
        // 上一次同 id 执行失败了：换新 command_id 重试
        pending.current = null;
        throw new Error("上次生成失败，请再试一次");
      }
      if (receipt.async_state === "stale") {
        // 上个进程留下的孤儿受理：换新 command_id 重新受理
        pending.current = null;
        push({ kind: "error", title: "生成中断", description: "上次生成中断，请再试一次" });
        setWaiting(null);
        return;
      }
      // accepted / pending / done 三态都等推进：轮询状态直到选角生效（真实
      // LLM 要跑完所有角色提议 + 验证，十几秒到几分钟）。
      const deadline = Date.now() + 300_000;
      for (;;) {
        if (Date.now() > deadline) {
          throw new Error("等待超过 5 分钟仍未完成，请稍后刷新重试");
        }
        await new Promise((r) => setTimeout(r, 1500));
        const status = await getStatus(sessionId);
        if (status.selected_role && status.stage !== "stage1_complete") {
          pending.current = null;
          router.push(`/game?id=${sessionId}`);
          return; // 等待态保持：跳转期间过场不撤、按钮仍禁用
        }
      }
    } catch (err) {
      push({
        kind: "error",
        title: "选角失败",
        description:
          err instanceof ApiError
            ? `${err.envelope.code}：${err.envelope.message}`
            : err instanceof Error
              ? err.message
              : String(err),
      });
      setWaiting(null);
    }
  }

  if (!sessionId) {
    return (
      <PageShell width="max-w-2xl">
        <Empty
          action={
            <Link href="/" className={buttonClass("outline", "sm")}>
              返回首页
            </Link>
          }
        >
          缺少会话参数。
        </Empty>
        <ToastHost />
      </PageShell>
    );
  }

  const ready = selectedRole !== null;
  const playable = new Set(
    characters.filter((c) => c.is_player_playable.value).map((c) => c.name)
  );
  for (const name of playableRoles) playable.add(name);

  return (
    <main
      data-surface="stage"
      data-effects={effects}
      className="flex h-screen w-full flex-col overflow-hidden bg-canvas"
    >
      <MotionRoot>
        <GameStage>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-6 sm:px-6 md:py-10">
              <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
                <div>
                  <p className="font-serif text-sm tracking-[0.3em] text-glow-gold">
                    {storeTitle ? `《${storeTitle}》` : "文境"}
                  </p>
                  <h1 className="mt-2 font-serif text-3xl tracking-[0.2em] text-ink md:text-4xl">
                    选择角色
                  </h1>
                  <p className="mt-2 text-sm text-ink-soft">
                    选一位走进课文。其余角色由 AI 来演，你说的话会改变他们的反应。
                  </p>
                </div>
                <Link href="/" className={buttonClass("quiet", "sm")} title={`会话 ${sessionId}`}>
                  返回首页
                </Link>
              </header>

              {ready && !submitting && (
                <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-flag/50 bg-glass px-4 py-3 backdrop-blur-md">
                  <Tag tone="flag">你</Tag>
                  <span className="text-sm text-ink">你已选定 {selectedRole}</span>
                  <Link
                    href={`/game?id=${sessionId}`}
                    className={buttonClass("glow", "sm", "ml-auto")}
                  >
                    进入舞台
                  </Link>
                </div>
              )}

              {characters.length === 0 ? (
                <Loading label="正在取回角色…" />
              ) : (
                <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
                  {characters.map((c) => (
                    <RoleCard
                      key={c.name}
                      profile={c}
                      playable={playable.has(c.name)}
                      selected={c.name === selectedRole}
                      submitting={submitting}
                      onSelect={() => handleSelect(c.name)}
                    />
                  ))}
                </div>
              )}
            </div>
          </div>
        </GameStage>

        <AnimatePresence>
          {waiting && (
            <FirstActWaiting
              key="waiting"
              role={waiting.role}
              scriptTitle={storeTitle}
              characters={characters}
              since={waiting.since}
            />
          )}
        </AnimatePresence>
      </MotionRoot>
      <ToastHost />
    </main>
  );
}

export default function RolesPage() {
  return (
    <Suspense
      fallback={
        <PageShell width="max-w-2xl">
          <Loading />
        </PageShell>
      }
    >
      <RolesContent />
    </Suspense>
  );
}
