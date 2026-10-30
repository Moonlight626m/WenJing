"use client";

import type { ReactNode } from "react";
import { useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { FormError } from "@/components/auth/form-error";
import { Button } from "@/components/ui/button";
import { Field, TextArea, TextInput } from "@/components/ui/field";
import {
  createScriptDraft,
  formatApiError,
  importSourceMaterial,
  startScriptGeneration,
} from "@/lib/api";
import type { MaterialPublic } from "@/lib/contracts/types";
import { CONTRACTS_SCHEMA_VERSION } from "@/lib/contracts/types";

/** 步骤序号挂在界行左侧，与剧本预览里的场景编号同一套版式语言。 */
function Step({
  index,
  title,
  children,
}: {
  index: number;
  title: string;
  children: ReactNode;
}) {
  return (
    <li className="flex gap-3">
      <span className="w-5 shrink-0 pt-1.5 text-right font-mono text-2xs text-ink-faint tabular-nums">
        {String(index).padStart(2, "0")}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-3 border-l border-rule pl-4">
        <h2 className="text-lg text-ink">{title}</h2>
        {children}
      </div>
    </li>
  );
}

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
        schema_version: CONTRACTS_SCHEMA_VERSION,
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
      <ol className="flex flex-col gap-8">
        <Step index={1} title="导入课文">
          <TextArea
            value={rawText}
            onChange={(e) => {
              setRawText(e.target.value);
              setFilename(null);
              setMaterial(null);
            }}
            placeholder="粘贴课文原文（戏剧 / 小说 / 叙事文均可）…"
            rows={10}
            aria-label="课文原文"
            className="w-full resize-y font-serif leading-[1.9]"
          />
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-ink-faint">
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
            <Button
              tone="outline"
              size="xs"
              onClick={() => fileRef.current?.click()}
            >
              上传 .txt / .md
            </Button>
            {filename && <span className="text-ink-soft">已选 {filename}</span>}
            <span className="font-mono tabular-nums">{rawText.length} 字</span>
          </div>
          <div>
            <Button
              tone="solid"
              size="sm"
              onClick={handleImport}
              disabled={importing || !rawText.trim()}
            >
              {importing ? "分析中…" : material ? "重新分析" : "导入并分析"}
            </Button>
          </div>
        </Step>

        {material && (
          <Step index={2} title="命名并生成">
            <p className="rounded-md border border-ok/50 bg-ok-wash px-3 py-2 text-xs text-ok">
              素材已导入 {material.title ?? "未命名"}（{material.char_count} 字）
            </p>
            <Field label="剧本名称">
              <TextInput
                value={name}
                onChange={(e) => setName(e.target.value)}
                maxLength={120}
                controlSize="sm"
                className="w-full"
              />
            </Field>
            <Field label="简介" hint="可选，展示在学生剧本广场">
              <TextArea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                maxLength={500}
                rows={2}
                controlSize="sm"
                className="w-full resize-y"
              />
            </Field>
            <div>
              <Button
                tone="accent"
                size="sm"
                onClick={handleCreate}
                disabled={creating || !name.trim()}
              >
                {creating ? "创建中…" : "创建并生成"}
              </Button>
            </div>
          </Step>
        )}
      </ol>

      <FormError message={error} />

      <Link href="/teacher" className="self-start text-sm text-accent underline">
        返回剧本库
      </Link>
    </div>
  );
}
