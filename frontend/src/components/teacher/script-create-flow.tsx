"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { FormError } from "@/components/auth/form-error";
import {
  createScriptDraft,
  formatApiError,
  importSourceMaterial,
  startScriptGeneration,
} from "@/lib/api";
import type { MaterialPublic } from "@/lib/contracts/types";

export function ScriptCreateFlow() {
  const router = useRouter();
  const fileRef = useRef<HTMLInputElement>(null);

  const [rawText, setRawText] = useState("");
  const [filename, setFilename] = useState<string | null>(null);
  const [material, setMaterial] = useState<MaterialPublic | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [importing, setImporting] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(file: File) {
    if (!/\.(txt|md)$/i.test(file.name)) {
      setError("仅支持 .txt / .md 文件");
      return;
    }
    setRawText(await file.text());
    setFilename(file.name);
    setMaterial(null);
    setError(null);
  }

  async function handleImport() {
    if (!rawText.trim() || importing) return;
    setImporting(true);
    setError(null);
    try {
      const result = await importSourceMaterial({
        schema_version: "1.0.0",
        source: filename ? "upload" : "paste",
        filename,
        raw_text: rawText,
      });
      setMaterial(result);
      if (result.title && !name.trim()) setName(result.title);
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setImporting(false);
    }
  }

  async function handleCreate() {
    if (!material || !name.trim() || creating) return;
    setCreating(true);
    setError(null);
    try {
      const script = await createScriptDraft({
        material_id: material.id,
        name: name.trim(),
        description: description.trim() || null,
      });
      // 立即触发后台生成；详情页轮询进度，创建即进入生成流程
      try {
        await startScriptGeneration(script.id);
      } catch {
        // 生成调度失败不阻塞：详情页仍可手动生成/重试
      }
      router.push(`/teacher/scripts/${script.id}`);
    } catch (err) {
      setError(formatApiError(err));
      setCreating(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-3 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <textarea
          value={rawText}
          onChange={(e) => {
            setRawText(e.target.value);
            setFilename(null);
            setMaterial(null);
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
            type="button"
            onClick={() => fileRef.current?.click()}
            className="rounded border border-zinc-300 px-3 py-1.5 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            上传 .txt / .md
          </button>
          {filename && <span>已选择：{filename}</span>}
          <span>{rawText.length} 字</span>
        </div>
        <div>
          <button
            type="button"
            onClick={handleImport}
            disabled={importing || !rawText.trim()}
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm text-white transition-opacity hover:opacity-85 disabled:opacity-50 dark:bg-zinc-100 dark:text-black"
          >
            {importing ? "分析中…" : material ? "重新分析" : "导入并分析"}
          </button>
        </div>
      </section>

      {material && (
        <section className="flex flex-col gap-3 rounded-xl border border-zinc-200 bg-white p-4 text-sm dark:border-zinc-800 dark:bg-zinc-900">
          <div className="rounded-lg border border-emerald-300 bg-emerald-50 px-3 py-2 text-xs text-emerald-700 dark:border-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">
            素材已导入：{material.title ?? "未命名"}（{material.char_count} 字）
          </div>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-zinc-400">剧本名称</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={120}
              className="rounded-lg border border-zinc-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-400 dark:border-zinc-700"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-zinc-400">简介（可选）</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={500}
              rows={2}
              className="resize-y rounded-lg border border-zinc-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-400 dark:border-zinc-700"
            />
          </label>
          <div>
            <button
              type="button"
              onClick={handleCreate}
              disabled={creating || !name.trim()}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white transition-opacity hover:opacity-85 disabled:opacity-50"
            >
              {creating ? "创建中…" : "创建并生成"}
            </button>
          </div>
        </section>
      )}

      <FormError message={error} />

      <Link
        href="/teacher"
        className="text-sm text-zinc-500 underline dark:text-zinc-400"
      >
        返回剧本库
      </Link>
    </div>
  );
}
