"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import {
  ApiError,
  generateScript,
  getStatus,
  importMaterial,
} from "@/lib/api";
import { genreLabel, GENERATION_PHASES, PHASE_LABELS, stageLabel } from "@/lib/labels";
import { upsertRecent } from "@/lib/session-cache";
import { useGameStore } from "@/stores/gameStore";
import { useUiStore } from "@/stores/uiStore";
import { ToastHost } from "@/components/toast-host";
import type { TextAnalysis } from "@/lib/contracts/types";

function ImportContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const sessionId = searchParams.get("id");

  const push = useUiStore((s) => s.push);
  const setScriptInfo = useGameStore((s) => s.setScriptInfo);

  const [stage, setStage] = useState<string | null>(null);
  const [rawText, setRawText] = useState("");
  const [filename, setFilename] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [analysis, setAnalysis] = useState<TextAnalysis | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generated, setGenerated] = useState(false);
  const [inlineError, setInlineError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!sessionId) return;
    getStatus(sessionId)
      .then((status) => {
        setStage(status.stage);
        if (status.stage === "stage1_complete" || status.stage.startsWith("stage2") || status.stage.startsWith("stage3")) {
          setGenerated(true);
        }
        upsertRecent({
          sessionId,
          stage: status.stage,
          title: null,
          playerRole: status.selected_role,
          updatedAt: new Date().toISOString(),
        });
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          push({ kind: "error", title: "会话不存在，请重新创建" });
          router.replace("/");
        }
      });
  }, [sessionId, push, router]);

  async function handleFile(file: File) {
    if (!/\.(txt|md)$/i.test(file.name)) {
      setInlineError("仅支持 .txt / .md 文件");
      return;
    }
    const text = await file.text();
    setRawText(text);
    setFilename(file.name);
    setInlineError(null);
  }

  async function handleImport() {
    if (!sessionId || !rawText.trim() || submitting) return;
    setSubmitting(true);
    setInlineError(null);
    try {
      const result = await importMaterial(sessionId, {
        schema_version: "1.0.0",
        source: filename ? "upload" : "paste",
        filename,
        raw_text: rawText,
      });
      setAnalysis(result);
      push({ kind: "success", title: "导入成功", description: `识别人物 ${result.characters.length} 个` });
    } catch (err) {
      setInlineError(err instanceof ApiError ? `${err.envelope.code}：${err.envelope.message}` : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleGenerate() {
    if (!sessionId || generating) return;
    setGenerating(true);
    setInlineError(null);
    try {
      const pkg = await generateScript(sessionId);
      setScriptInfo(pkg);
      setGenerated(true);
      setStage("stage1_complete");
      upsertRecent({
        sessionId,
        stage: "stage1_complete",
        title: pkg.title,
        playerRole: null,
        updatedAt: new Date().toISOString(),
      });
      push({ kind: "success", title: `剧本已生成：${pkg.title}` });
    } catch (err) {
      setInlineError(err instanceof ApiError ? `${err.envelope.code}：${err.envelope.message}` : String(err));
    } finally {
      setGenerating(false);
    }
  }

  if (!sessionId) {
    return (
      <main className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
        <p>缺少会话参数，请从首页开始。</p>
        <Link href="/" className="text-blue-600 underline dark:text-blue-400">
          返回首页
        </Link>
        <ToastHost />
      </main>
    );
  }

  const alreadyGenerated = generated || (stage !== null && stage !== "init" && stage !== "stage1_creating");

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 p-6">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">导入课文</h1>
        <span className="text-xs text-zinc-400">
          {sessionId.slice(0, 8)} · {stage ? stageLabel(stage) : "检查中…"}
        </span>
      </header>

      {alreadyGenerated && (
        <div className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm dark:border-emerald-700 dark:bg-emerald-950/40">
          剧本已生成。
          <Link href={`/roles?id=${sessionId}`} className="ml-2 text-emerald-700 underline dark:text-emerald-300">
            前去选角 →
          </Link>
        </div>
      )}

      <section className="flex flex-col gap-3 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <textarea
          value={rawText}
          onChange={(e) => {
            setRawText(e.target.value);
            setFilename(null);
          }}
          placeholder="粘贴课文原文…（戏剧 / 小说 / 叙事文）"
          rows={8}
          className="w-full resize-y rounded-lg border border-zinc-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-400 dark:border-zinc-700"
        />
        <div className="flex items-center gap-3 text-xs text-zinc-500 dark:text-zinc-400">
          <input
            ref={fileRef}
            type="file"
            accept=".txt,.md"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleFile(file);
            }}
          />
          <button
            onClick={() => fileRef.current?.click()}
            className="rounded border border-zinc-300 px-3 py-1.5 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            上传 .txt / .md
          </button>
          {filename && <span>已选择：{filename}</span>}
          <span>{rawText.length} 字</span>
        </div>
        {inlineError && (
          <p className="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-950/50 dark:text-red-300">
            {inlineError}
          </p>
        )}
        <div className="flex gap-2">
          <button
            onClick={handleImport}
            disabled={submitting || !rawText.trim()}
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm text-white transition-opacity hover:opacity-85 disabled:opacity-50 dark:bg-zinc-100 dark:text-black"
          >
            {submitting ? "分析中…" : analysis ? "重新分析" : "导入并分析"}
          </button>
        </div>
      </section>

      {analysis && (
        <section className="flex flex-col gap-3 rounded-xl border border-zinc-200 bg-white p-4 text-sm dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex items-center justify-between">
            <h2 className="font-medium">原文分析</h2>
            <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800">
              {genreLabel(analysis.genre.genre)}
              {analysis.genre.is_supported ? "" : "（暂不支持演绎）"}
            </span>
          </div>
          {analysis.title && (
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              篇目：{analysis.title}
              {analysis.author ? ` · ${analysis.author}` : ""}
            </p>
          )}
          <div>
            <h3 className="mb-1 text-xs text-zinc-400">人物（{analysis.characters.length}）</h3>
            <ul className="flex flex-col gap-1">
              {analysis.characters.map((c) => (
                <li key={c.name} className="text-zinc-700 dark:text-zinc-300">
                  <span className="font-medium">{c.name}</span>
                  {c.role && <span className="text-xs text-zinc-400"> · {c.role}</span>}
                  {c.personality && <span className="text-xs text-zinc-400"> · {c.personality}</span>}
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="mb-1 text-xs text-zinc-400">场景（{analysis.scenes.length}）</h3>
            <ul className="list-inside list-disc text-zinc-700 dark:text-zinc-300">
              {analysis.scenes.map((s) => (
                <li key={s.title}>{s.title}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3 className="mb-1 text-xs text-zinc-400">关键事件（{analysis.key_events.length}）</h3>
            <ol className="list-inside list-decimal text-zinc-700 dark:text-zinc-300">
              {analysis.key_events
                .slice()
                .sort((a, b) => a.order - b.order)
                .map((k) => (
                  <li key={k.order}>{k.title}</li>
                ))}
            </ol>
          </div>

          <div className="mt-2 border-t border-zinc-200 pt-3 dark:border-zinc-800">
            {alreadyGenerated ? (
              <Link
                href={`/roles?id=${sessionId}`}
                className="inline-block rounded-lg bg-blue-600 px-4 py-2 text-sm text-white transition-opacity hover:opacity-85"
              >
                前去选角 →
              </Link>
            ) : (
              <button
                onClick={handleGenerate}
                disabled={generating}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white transition-opacity hover:opacity-85 disabled:opacity-50"
              >
                {generating ? "生成中…" : "生成剧本"}
              </button>
            )}
            {generating && (
              <div className="mt-3 flex flex-col gap-1">
                {GENERATION_PHASES.map((phase, i) => (
                  <div key={phase} className="flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
                    <span
                      className={`inline-block h-1.5 w-1.5 rounded-full ${
                        i === 2 ? "animate-pulse bg-blue-500" : "bg-zinc-300 dark:bg-zinc-700"
                      }`}
                    />
                    {PHASE_LABELS[phase]}
                    {phase === "generate" && "（真实 LLM 模式下可能需要 1-2 分钟）"}
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      )}
      <ToastHost />
    </main>
  );
}

export default function ImportPage() {
  return (
    <Suspense fallback={<p className="p-8 text-zinc-500">加载中…</p>}>
      <ImportContent />
    </Suspense>
  );
}
