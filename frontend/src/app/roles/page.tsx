"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { ApiError, getScriptDetail, getStatus, submitAsyncCommandRest } from "@/lib/api";
import { buildCommand } from "@/lib/session-cache";
import { useGameStore } from "@/stores/gameStore";
import { useUiStore } from "@/stores/uiStore";
import { ToastHost } from "@/components/toast-host";
import { Button, buttonClass } from "@/components/ui/button";
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

  const [playableRoles, setPlayableRoles] = useState<string[]>([]);
  const [selectedRole, setSelectedRole] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // 超时/失败后的重试复用同一 command_id：服务端可能已经跑完并落库，命令表的幂等
  // 闸据此返回首次结果，而不是再跑一轮（选角后立刻重跑会多推一个 beat）。
  const pending = useRef<{ role: string; command: PlayerCommand } | null>(null);

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
    setSubmitting(true);
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
        setSubmitting(false);
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
          return; // setSubmitting 保持：跳转动画期间按钮仍禁用
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
      setSubmitting(false);
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

  return (
    <PageShell width="max-w-2xl">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2 border-b border-rule pb-3">
        <div>
          <h1 className="text-2xl text-ink">选择角色</h1>
          {storeTitle && (
            <p className="mt-1 text-sm text-ink-soft">剧本《{storeTitle}》</p>
          )}
        </div>
        <span className="font-mono text-2xs text-ink-faint">
          {sessionId.slice(0, 8)}
        </span>
      </header>

      {submitting && (
        <p className="measure text-sm text-ink-soft">
          正在为所有角色生成首幕（含提议与校验），通常十几秒到几分钟，请勿关闭页面——
          会话状态已保存，随时可回来。
        </p>
      )}

      {ready && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-flag/50 bg-flag-wash px-4 py-3">
          <Tag tone="flag">你</Tag>
          <span className="text-sm text-ink">你已扮演 {selectedRole}</span>
          <Link
            href={`/game?id=${sessionId}`}
            className={buttonClass("accent", "sm", "ml-auto")}
          >
            进入舞台
          </Link>
        </div>
      )}

      <div className="flex flex-col gap-3">
        {characters.length === 0 && <Loading label="正在取回角色…" />}
        {characters.map((c) => {
          const isSelected = c.name === selectedRole;
          return (
            <div
              key={c.name}
              // 选中态用一道朱砂界行标记，而不是整块染色——上方横幅已经用底色说了
              // 同一件事，两处都填色就只剩热闹，朱砂也就不再是标记。
              className={`relative flex flex-wrap items-start justify-between gap-x-5 gap-y-3 overflow-hidden rounded-lg border p-4 pl-5 transition-colors ${
                isSelected ? "border-flag/50 bg-surface" : "border-rule bg-surface"
              }`}
            >
              {isSelected && (
                <span aria-hidden className="absolute inset-y-0 left-0 w-0.5 bg-flag" />
              )}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-serif text-lg text-ink">{c.name}</span>
                  {c.is_player_playable.value && <Tag tone="accent">可扮演</Tag>}
                  {isSelected && <Tag tone="flag">你</Tag>}
                </div>
                {c.public_background && (
                  <p className="measure mt-2 text-sm text-ink-soft">
                    {c.public_background}
                  </p>
                )}
                {c.personality_traits.length > 0 && (
                  <p className="mt-2 text-xs text-ink-faint">
                    {c.personality_traits.map((t) => t.label).join("、")}
                  </p>
                )}
              </div>
              <Button
                tone={isSelected ? "outline" : "accent"}
                size="sm"
                onClick={() => handleSelect(c.name)}
                disabled={submitting || isSelected}
              >
                {isSelected ? "已选" : submitting ? "生成首幕中…" : "扮演此角色"}
              </Button>
            </div>
          );
        })}
      </div>
      <ToastHost />
    </PageShell>
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
