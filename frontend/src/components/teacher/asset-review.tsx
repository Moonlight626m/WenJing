"use client";

import { Fragment, useRef } from "react";

import { ASSET_IMAGE_BG, AssetImage } from "@/components/asset-image";
import { Button } from "@/components/ui/button";
import { Tag } from "@/components/ui/tag";
import { formatApiError, uploadScriptAsset } from "@/lib/api";
import { useUiStore } from "@/stores/uiStore";
import type { AssetOp, AssetRef, CharacterProfile, Scene } from "@/lib/contracts/types";
import { CONTRACTS_SCHEMA_VERSION } from "@/lib/contracts/types";

const CARD = "flex gap-3 rounded-lg border border-warn/45 bg-warn-wash/40 p-2.5";

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
  const push = useUiStore((s) => s.push);
  const fileRef = useRef<HTMLInputElement | null>(null);
  // 待生效意图可能把「刚上传的图」合成进缩略图；URL 换取与降级由 AssetImage 负责
  const shown = pendingRef(asset, op);

  if (op?.op === "remove") {
    return (
      <div className={CARD}>
        <div className="flex flex-1 flex-col items-start gap-1.5">
          <span className="text-xs font-medium text-ink">{label}</span>
          <p className="text-xs text-ink-soft">
            已标记删除（通过后生效；资产行保留，可再重新生成找回）
          </p>
          <Button tone="outline" size="xs" disabled={disabled} onClick={() => onChange(null)}>
            撤销删除
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className={CARD}>
      <AssetImage
        asset={shown}
        alt={label}
        className={`h-20 w-32 shrink-0 rounded-sm ${ASSET_IMAGE_BG}`}
        emptyLabel="无图（纯文本游玩）"
        placeholderClassName="text-2xs text-ink-faint"
      />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <span className="text-xs font-medium text-ink">{label}</span>
        <div className="flex flex-wrap gap-1.5">
          <Button
            tone="outline"
            size="xs"
            disabled={disabled}
            onClick={() =>
              onChange({
                schema_version: CONTRACTS_SCHEMA_VERSION,
                op: "regenerate",
                subject_key: subjectKey,
                kind,
              })
            }
          >
            重新生成
          </Button>
          <Button
            tone="outline"
            size="xs"
            disabled={disabled}
            onClick={() =>
              onChange({
                schema_version: CONTRACTS_SCHEMA_VERSION,
                op: "search_replace",
                subject_key: subjectKey,
                kind,
              })
            }
          >
            检索替换
          </Button>
          <Button
            tone="outline"
            size="xs"
            disabled={disabled}
            onClick={() => fileRef.current?.click()}
          >
            上传自有
          </Button>
          {asset && (
            <Button
              tone="danger"
              size="xs"
              disabled={disabled}
              onClick={() =>
                onChange({
                  schema_version: CONTRACTS_SCHEMA_VERSION,
                  op: "remove",
                  subject_key: subjectKey,
                  kind,
                })
              }
            >
              删除
            </Button>
          )}
        </div>
        {op && (
          <p className="flex items-center gap-2 text-2xs text-ok">
            待生效 {OP_LABELS[op.op]}
            <button type="button" className="text-accent underline" onClick={() => onChange(null)}>
              撤销
            </button>
          </p>
        )}
        {asset?.status === "failed" && !op && (
          <p className="text-2xs text-ink-faint">
            生成失败，可用「重新生成 / 检索替换 / 上传」补图，或无图游玩。
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
            .catch((err) =>
              push({
                kind: "error",
                title: "上传配图失败",
                description: formatApiError(err),
              })
            );
        }}
      />
    </div>
  );
}

/** 终审配图审批区（#50）：场景场面图（含分支）+ 人物头像。 */
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
    <div className="flex flex-col gap-3">
      <p className="measure text-xs text-warn">
        配图审批：自动配图已完成，可逐槽重新生成 / 检索替换 / 上传 / 删除，通过后生效。
        建议先审人物头像（它是各场景图的参考图），再审各场景——头像换脸后场景应重绘。
      </p>
      {/* 章节式分组：先人物（角色卡，一致性源头），再按场景逐章审其场面与分支 */}
      <section className="flex flex-col gap-1.5">
        <h4 className="text-xs font-medium text-ink">人物头像（角色一致性的源头）</h4>
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
      </section>
      <section className="flex flex-col gap-1.5">
        <h4 className="text-xs font-medium text-ink">场景场面图（按章节）</h4>
        {scenes.map((scene) => {
          const subjectKey = `scene:${scene.scene_id}`;
          // 旧脚本的槽位是纯空镜 background；新生成的是含人物的 scene_montage。
          // 槽位操作的 kind 必须与现有资产对齐，否则「重新生成」会改错槽。
          const kind: AssetOp["kind"] =
            scene.background_asset?.kind === "background"
              ? "background"
              : "scene_montage";
          const sceneOps = [
            assetOpKey(subjectKey, kind),
            ...(scene.branches ?? []).map((b) =>
              assetOpKey(`${subjectKey}::branch:${b.branch_id}`, "scene_montage")
            ),
          ];
          const hasPending = sceneOps.some((k) => drafts.get(k));
          return (
            <Fragment key={subjectKey}>
              <p className="flex items-center gap-2 text-2xs text-ink-faint">
                <span className="font-medium text-ink-soft">{scene.title}</span>
                {hasPending && <Tag tone="warn">有改动</Tag>}
              </p>
              <AssetSlotCard
                label={
                  kind === "background"
                    ? `背景（空镜）`
                    : `场面图（含在场人物）`
                }
                subjectKey={subjectKey}
                kind={kind}
                asset={scene.background_asset ?? null}
                op={drafts.get(assetOpKey(subjectKey, kind)) ?? null}
                scriptId={scriptId}
                onChange={(op) => setOp(subjectKey, kind, op)}
                disabled={disabled}
              />
              {(scene.branches ?? []).map((branch) => {
                const branchKey = `${subjectKey}::branch:${branch.branch_id}`;
                return (
                  <AssetSlotCard
                    key={branchKey}
                    label={`分支「${branch.title}」场面图`}
                    subjectKey={branchKey}
                    kind="scene_montage"
                    asset={branch.background_asset ?? null}
                    op={drafts.get(assetOpKey(branchKey, "scene_montage")) ?? null}
                    scriptId={scriptId}
                    onChange={(op) => setOp(branchKey, "scene_montage", op)}
                    disabled={disabled}
                  />
                );
              })}
            </Fragment>
          );
        })}
      </section>
    </div>
  );
}
