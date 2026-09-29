"use client";

import { useEffect, useRef, useState } from "react";

import { fetchAssetUrl, uploadScriptAsset } from "@/lib/api";
import type { AssetOp, AssetRef, CharacterProfile, Scene } from "@/lib/contracts/types";
import { CONTRACTS_SCHEMA_VERSION } from "@/lib/contracts/types";

const CARD =
  "flex gap-2 rounded-lg border border-amber-200 p-2 dark:border-amber-900";
const OP_BUTTON =
  "rounded border border-amber-300 px-2 py-0.5 text-xs transition-colors hover:bg-amber-100 disabled:opacity-50 dark:border-amber-800 dark:hover:bg-amber-900/40";

const OP_LABELS: Record<AssetOp["op"], string> = {
  remove: "删除配图",
  regenerate: "重新生成",
  search_replace: "检索替换",
  bind_upload: "使用上传图片",
};

/** 各槽位的教师意图（key = subject_key|kind；值为 null 表示撤销过回到未操作）。 */
export type AssetOpDrafts = Map<string, AssetOp | null>;

export function assetOpKey(subjectKey: string, kind: string): string {
  return `${subjectKey}|${kind}`;
}

/** 汇总进 GateEdits.asset_ops（跳过 null=已撤销的条目）。 */
export function collectAssetOps(drafts: AssetOpDrafts): AssetOp[] {
  return [...drafts.values()].filter((op): op is AssetOp => op !== null);
}

function pendingRef(
  asset: AssetRef | null,
  op: AssetOp | null
): AssetRef | null {
  if (op?.op === "bind_upload" && op.asset_id) {
    return { asset_id: op.asset_id, kind: op.kind, status: "ready" };
  }
  return asset;
}

/** 单槽位配图审批卡：缩略图 + 重新生成/检索替换/上传/删除（#50）。 */
function AssetSlotCard({
  label,
  subjectKey,
  kind,
  asset,
  op,
  scriptId,
  onChange,
  disabled,
}: {
  label: string;
  subjectKey: string;
  kind: AssetOp["kind"];
  asset: AssetRef | null;
  op: AssetOp | null;
  scriptId: number;
  onChange: (op: AssetOp | null) => void;
  disabled: boolean;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const shown = pendingRef(asset, op);
  // 渲染期间重置派生状态（React「props 变化时调整 state」模式）：意图或
  // 资产变化时旧的 URL/错误态立刻失效，再由 effect 异步拉取新地址。
  const [lastShown, setLastShown] = useState<AssetRef | null>(shown);
  if (shown !== lastShown) {
    setLastShown(shown);
    setUrl(null);
    setLoadFailed(false);
  }

  // 预签名 URL 短时效：意图/资产变化后现取，不做跨会话缓存
  useEffect(() => {
    let active = true;
    if (!shown || shown.status !== "ready") return;
    fetchAssetUrl(shown.asset_id)
      .then((res) => {
        if (active) setUrl(res.url);
      })
      .catch(() => {
        if (active) setLoadFailed(true); // 无图降级：占位文案
      });
    return () => {
      active = false;
    };
  }, [shown]);

  if (op?.op === "remove") {
    return (
      <div className={CARD}>
        <div className="flex flex-1 flex-col gap-1">
          <span className="text-xs font-medium">{label}</span>
          <p className="text-xs text-amber-700/70 dark:text-amber-300/70">
            已标记删除（通过后生效；资产行保留，可再重新生成找回）
          </p>
          <button type="button" disabled={disabled} onClick={() => onChange(null)} className={OP_BUTTON}>
            撤销删除
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={CARD}>
      <div className="h-20 w-32 shrink-0 overflow-hidden rounded bg-amber-100/60 dark:bg-amber-900/30">
        {url ? (
          // 预签名 URL 含凭证查询参数且短时效，仅本次审阅显示
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url} alt={label} className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full items-center justify-center px-1 text-center text-[10px] text-amber-700/60 dark:text-amber-300/60">
            {loadFailed
              ? "图片暂不可用"
              : shown
                ? "加载中…"
                : "无图（纯文本游玩）"}
          </div>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-1">
        <span className="text-xs font-medium">{label}</span>
        <div className="flex flex-wrap gap-1">
          <button
            type="button"
            disabled={disabled}
            onClick={() =>
              onChange({
                schema_version: CONTRACTS_SCHEMA_VERSION,
                op: "regenerate",
                subject_key: subjectKey,
                kind,
              })
            }
            className={OP_BUTTON}
          >
            重新生成
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() =>
              onChange({
                schema_version: CONTRACTS_SCHEMA_VERSION,
                op: "search_replace",
                subject_key: subjectKey,
                kind,
              })
            }
            className={OP_BUTTON}
          >
            检索替换
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={() => fileRef.current?.click()}
            className={OP_BUTTON}
          >
            上传自有
          </button>
          {asset && (
            <button
              type="button"
              disabled={disabled}
              onClick={() =>
                onChange({
                  schema_version: CONTRACTS_SCHEMA_VERSION,
                  op: "remove",
                  subject_key: subjectKey,
                  kind,
                })
              }
              className={OP_BUTTON}
            >
              删除
            </button>
          )}
        </div>
        {op && (
          <p className="text-[10px] text-emerald-700 dark:text-emerald-400">
            待生效：{OP_LABELS[op.op]}
            <button type="button" className="ml-2 underline" onClick={() => onChange(null)}>
              撤销
            </button>
          </p>
        )}
        {asset?.status === "failed" && !op && (
          <p className="text-[10px] text-amber-700/70 dark:text-amber-300/70">
            生成失败：可用「重新生成/检索替换/上传」补图，或无图游玩。
          </p>
        )}
      </div>
      <input
        ref={fileRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (!file) return;
          void uploadScriptAsset(scriptId, { subjectKey, kind, file })
            .then((ref) =>
              onChange({
                schema_version: CONTRACTS_SCHEMA_VERSION,
                op: "bind_upload",
                subject_key: subjectKey,
                kind,
                asset_id: ref.asset_id,
              })
            )
            .catch(() => setLoadFailed(true));
        }}
      />
    </div>
  );
}

/** 终审配图审批区（#50）：场景背景 + 人物头像两组槽位。 */
export function AssetReviewSection({
  scriptId,
  scenes,
  characters,
  drafts,
  onDraftsChange,
  disabled,
}: {
  scriptId: number;
  scenes: Scene[];
  characters: CharacterProfile[];
  drafts: AssetOpDrafts;
  onDraftsChange: (next: AssetOpDrafts) => void;
  disabled: boolean;
}) {
  function setOp(subjectKey: string, kind: AssetOp["kind"], op: AssetOp | null) {
    const next = new Map(drafts);
    next.set(assetOpKey(subjectKey, kind), op);
    onDraftsChange(next);
  }

  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs font-medium text-amber-700 dark:text-amber-300">
        配图审批（自动配图已完成；可逐槽重新生成/检索替换/上传/删除，通过后生效）
      </span>
      {scenes.map((scene) => {
        const subjectKey = `scene:${scene.scene_id}`;
        return (
          <AssetSlotCard
            key={subjectKey}
            label={`场景「${scene.title}」背景`}
            subjectKey={subjectKey}
            kind="background"
            asset={scene.background_asset ?? null}
            op={drafts.get(assetOpKey(subjectKey, "background")) ?? null}
            scriptId={scriptId}
            onChange={(op) => setOp(subjectKey, "background", op)}
            disabled={disabled}
          />
        );
      })}
      {characters.map((character) => {
        const subjectKey = `character:${character.name}`;
        return (
          <AssetSlotCard
            key={subjectKey}
            label={`人物「${character.name}」头像`}
            subjectKey={subjectKey}
            kind="avatar"
            asset={character.avatar_asset ?? null}
            op={drafts.get(assetOpKey(subjectKey, "avatar")) ?? null}
            scriptId={scriptId}
            onChange={(op) => setOp(subjectKey, "avatar", op)}
            disabled={disabled}
          />
        );
      })}
    </div>
  );
}
