"use client";

import { useState, type ReactNode } from "react";

import {
  AssetReviewSection,
  collectAssetOps,
  type AssetOpDrafts,
} from "@/components/teacher/asset-review";
import { Button } from "@/components/ui/button";
import { controlClass } from "@/components/ui/field";
import { Tag } from "@/components/ui/tag";
import type {
  CharacterProfile,
  GateEdits,
  GateReview,
  MaterialDossier,
  ScriptPackage,
} from "@/lib/contracts/types";
import { CONTRACTS_SCHEMA_VERSION } from "@/lib/contracts/types";

const FIELD = controlClass("sm", "w-full");
const LABEL = "text-xs text-ink-soft";

/** 闸门面板的分区卡：标题 + 可选副标 + 内容（视觉切割避免产物/指令/操作混排）。 */
function PanelBlock({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-rule bg-surface p-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-rule pb-2">
        <h3 className="text-sm text-ink">{title}</h3>
        {hint && <span className="text-xs text-ink-faint">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

export interface GateResumePayload {
  directives: string[];
  edits: GateEdits;
  action: "approve" | "reject";
  /** #50：上传等异步操作可能需要知道剧本 id（门面板从详情页获得）。 */
  scriptId?: number;
}

const GATE_TITLES: Record<string, string> = {
  materials: "素材审阅",
  pre_write: "人物与场景审定",
  final: "剧本终审",
};

const GATE_HINTS: Record<string, string> = {
  materials:
    "素材收集与考证已通过。可直接编辑时代背景/世界观等素材结论（编辑稿直接用于下游生成），也可附加指导指令；素材区默认折叠，点「展开素材」查看与修改。",
  pre_write:
    "事件划分与人物设定已完成。可编辑场景名称、参与人物与人物形象，审定后进入剧本书写；也可附加指导指令。",
  final:
    "总审已通过。可编辑剧本标题与场景名，通过即落库；或填写打回意见退回剧本书写重做一轮。",
};

/** 教师闸门审阅面板（#34）：按闸门位置展示中间产物，支持编辑与指导。 */
export function GateReviewPanel({
  scriptId,
  review,
  busy,
  onResume,
}: {
  scriptId?: number;
  review: GateReview | null;
  busy: string | null;
  onResume: (payload: GateResumePayload) => void;
}) {
  // 旧行没有审阅载荷：退化为纯指导文本（素材闸门）
  const gate = review?.gate ?? "materials";
  const [lastReview, setLastReview] = useState<GateReview | null>(review);
  const [directives, setDirectives] = useState("");
  const [materialsOpen, setMaterialsOpen] = useState(false);
  const [dossier, setDossier] = useState<MaterialDossier | null>(
    review?.dossier ?? null
  );
  const [profiles, setProfiles] = useState<CharacterProfile[]>(
    review?.profiles ?? []
  );
  const [sceneTitles, setSceneTitles] = useState<string[]>(
    (review?.division?.scenes ?? []).map((s) => s.title)
  );
  const [sceneParticipants, setSceneParticipants] = useState<string[]>(
    (review?.division?.scenes ?? []).map((s) => s.participants.join("、"))
  );
  const [packageDraft, setPackageDraft] = useState<ScriptPackage | null>(
    review?.package ?? null
  );
  // #50 配图审批：槽位 → 教师意图（仅在 final 闸门使用）
  const [assetOpDrafts, setAssetOpDrafts] = useState<AssetOpDrafts>(
    () => new Map()
  );

  // 草稿随新审阅载荷重置（React「props 变化时调整 state」模式：
  // 渲染期间同步，不进 effect）。终审打回重停时 key 不变也能拿到新稿。
  if (review !== lastReview) {
    setLastReview(review);
    setDossier(review?.dossier ?? null);
    setProfiles(review?.profiles ?? []);
    const scenes = review?.division?.scenes ?? [];
    setSceneTitles(scenes.map((s) => s.title));
    setSceneParticipants(scenes.map((s) => s.participants.join("、")));
    setPackageDraft(review?.package ?? null);
    setMaterialsOpen(false);
    setAssetOpDrafts(new Map());
  }

  const directiveList = directives
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

  /** 教师未改动的产物置 null（GateEdits「未提供的字段视为未编辑」）。 */
  function editedOr<T>(draft: T | null, original: T | null | undefined): T | null {
    if (draft === null || original === null || original === undefined) return null;
    return JSON.stringify(draft) === JSON.stringify(original) ? null : draft;
  }

  function buildResume(action: "approve" | "reject"): GateResumePayload {
    const empty: GateEdits = {
      schema_version: CONTRACTS_SCHEMA_VERSION,
      dossier: null,
      division: null,
      profiles: null,
      package: null,
      asset_ops: [],
    };
    if (gate === "materials") {
      return {
        directives: directiveList,
        edits: { ...empty, dossier: editedOr(dossier, review?.dossier ?? null) },
        action,
      };
    }
    if (gate === "pre_write") {
      const division = review?.division;
      const divisionDraft = division
        ? {
            scenes: division.scenes.map((scene, i) => ({
              ...scene,
              title: sceneTitles[i]?.trim() || scene.title,
              participants: splitList(sceneParticipants[i] ?? ""),
            })),
          }
        : null;
      return {
        directives: directiveList,
        edits: {
          ...empty,
          division: editedOr(divisionDraft, division ?? null),
          profiles: editedOr(profiles, review?.profiles ?? null),
        },
        action,
      };
    }
    return {
      directives: directiveList,
      edits: {
        ...empty,
        package: editedOr(packageDraft, review?.package ?? null),
        asset_ops: gate === "final" ? collectAssetOps(assetOpDrafts) : [],
      },
      action,
    };
  }

  const isFinal = gate === "final";

  return (
    <section className="flex flex-col gap-4 rounded-lg border border-warn/50 bg-warn-wash/50 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <Tag tone="warn">闸门暂停</Tag>
        <h2 className="text-lg text-ink">{GATE_TITLES[gate]}</h2>
      </div>
      <p className="measure text-xs text-ink-soft">{GATE_HINTS[gate]}</p>

      {gate === "materials" && (
        <PanelBlock title="素材结论" hint="编辑稿直接用于下游生成，不重新考证">
          <Button
            tone="outline"
            size="xs"
            className="self-start"
            onClick={() => setMaterialsOpen((open) => !open)}
          >
            {materialsOpen ? "收起素材" : "展开素材"}
          </Button>
          {materialsOpen &&
            (dossier ? (
              <DossierEditor dossier={dossier} onChange={setDossier} />
            ) : (
              <p className="text-xs text-ink-faint">
                本次生成未提供可编辑的素材结论。
              </p>
            ))}
          {materialsOpen && review && review.evidence.length > 0 && (
            <EvidenceList items={review.evidence} />
          )}
        </PanelBlock>
      )}

      {gate === "pre_write" && (
        <>
          {review?.division && (
            <PanelBlock title="场景划分" hint="可编辑场景名与参与人物">
              {review.division.scenes.map((scene, i) => (
                <div
                  key={i}
                  className="flex flex-col gap-2 rounded-md border border-rule p-2.5"
                >
                  <input
                    value={sceneTitles[i] ?? scene.title}
                    onChange={(e) =>
                      setSceneTitles((prev) => {
                        const next = [...prev];
                        next[i] = e.target.value;
                        return next;
                      })
                    }
                    className={`${FIELD} font-serif`}
                    aria-label={`场景 ${i + 1} 名称`}
                  />
                  <input
                    value={sceneParticipants[i] ?? scene.participants.join("、")}
                    onChange={(e) =>
                      setSceneParticipants((prev) => {
                        const next = [...prev];
                        next[i] = e.target.value;
                        return next;
                      })
                    }
                    className={FIELD}
                    aria-label={`场景 ${i + 1} 参与人物`}
                    placeholder="参与人物（用顿号或逗号分隔）"
                  />
                  <p className="text-xs text-ink-faint">
                    {scene.beats.map((beat) => beat.description).join(" → ")}
                  </p>
                </div>
              ))}
            </PanelBlock>
          )}
          {profiles.length > 0 && (
            <PanelBlock title="人物设定" hint="可编辑形象与语言风格">
              {profiles.map((profile, i) => (
                <div
                  key={profile.name}
                  className="flex flex-col gap-2 rounded-md border border-rule p-2.5"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <span className="font-serif text-base text-ink">{profile.name}</span>
                    <label className="flex items-center gap-2 text-xs text-ink-soft">
                      <input
                        type="checkbox"
                        checked={profile.is_player_playable.value}
                        onChange={(e) =>
                          setProfiles((prev) => {
                            const next = [...prev];
                            next[i] = {
                              ...profile,
                              is_player_playable: {
                                ...profile.is_player_playable,
                                value: e.target.checked,
                              },
                            };
                            return next;
                          })
                        }
                      />
                      可扮演
                    </label>
                  </div>
                  <textarea
                    value={profile.public_background}
                    onChange={(e) =>
                      setProfiles((prev) => {
                        const next = [...prev];
                        next[i] = { ...profile, public_background: e.target.value };
                        return next;
                      })
                    }
                    rows={2}
                    className={`${FIELD} resize-y`}
                    aria-label={`${profile.name} 人物背景`}
                    placeholder="人物背景"
                  />
                  <input
                    value={
                      profile.speech_style
                        ? [
                            profile.speech_style.era_layer,
                            profile.speech_style.sentence_rhythm,
                            profile.speech_style.address_terms,
                            profile.speech_style.catchphrases,
                            profile.speech_style.emotion_expression,
                          ]
                            .filter(Boolean)
                            .join("；")
                        : ""
                    }
                    onChange={(e) =>
                      setProfiles((prev) => {
                        const next = [...prev];
                        const style = profile.speech_style ?? {
                          era_layer: "",
                          sentence_rhythm: "",
                          address_terms: "",
                          catchphrases: "",
                          emotion_expression: "",
                          sample_lines: [],
                        };
                        next[i] = {
                          ...profile,
                          speech_style: { ...style, era_layer: e.target.value || "" },
                        };
                        return next;
                      })
                    }
                    className={FIELD}
                    aria-label={`${profile.name} 语言时代层`}
                    placeholder="语言时代层（可选；五要素在结构化编辑中维护）"
                  />
                </div>
              ))}
            </PanelBlock>
          )}
        </>
      )}

      {isFinal && packageDraft && (
        <PanelBlock title="剧本内容" hint="可编辑标题与场景名，通过即落库">
          <label className="flex flex-col gap-1.5">
            <span className={LABEL}>剧本标题</span>
            <input
              value={packageDraft.title}
              onChange={(e) =>
                setPackageDraft({ ...packageDraft, title: e.target.value })
              }
              className={`${FIELD} font-serif`}
            />
          </label>
          {packageDraft.scenes.map((scene, i) => (
            <label key={scene.scene_id} className="flex flex-col gap-1.5">
              <span className={LABEL}>场景 {i + 1} 名称</span>
              <input
                value={scene.title}
                onChange={(e) =>
                  setPackageDraft({
                    ...packageDraft,
                    scenes: packageDraft.scenes.map((s, j) =>
                      j === i ? { ...s, title: e.target.value } : s
                    ),
                  })
                }
                className={`${FIELD} font-serif`}
              />
            </label>
          ))}
        </PanelBlock>
      )}

      {isFinal && packageDraft && (
        <PanelBlock title="配图审批" hint="逐槽重新生成 / 检索替换 / 上传 / 删除，通过后生效">
          <AssetReviewSection
            scriptId={scriptId ?? 0}
            scenes={packageDraft.scenes}
            characters={packageDraft.characters}
            drafts={assetOpDrafts}
            onDraftsChange={setAssetOpDrafts}
            disabled={busy !== null}
          />
        </PanelBlock>
      )}

      <PanelBlock title={isFinal ? "打回指导意见" : "指导指令"} hint="每行一条，可选">
        <textarea
          value={directives}
          onChange={(e) => setDirectives(e.target.value)}
          rows={3}
          aria-label={isFinal ? "打回指导意见" : "指导指令"}
          placeholder={
            isFinal
              ? "例如：\n结尾要落在父亲转身之后"
              : "例如：\n孔乙己的迂腐要更突出"
          }
          className={`${FIELD} resize-y font-serif leading-[1.9]`}
        />
      </PanelBlock>

      <div className="flex flex-wrap items-center gap-3">
        {isFinal ? (
          <>
            <Button
              tone="ok"
              size="md"
              onClick={() => onResume(buildResume("approve"))}
              disabled={busy !== null}
            >
              {busy === "resume" ? "处理中…" : "通过并落库"}
            </Button>
            <Button
              tone="danger"
              size="md"
              onClick={() => onResume(buildResume("reject"))}
              disabled={busy !== null}
            >
              打回重写
            </Button>
          </>
        ) : (
          <Button
            tone="accent"
            size="md"
            onClick={() => onResume(buildResume("approve"))}
            disabled={busy !== null}
          >
            {busy === "resume" ? "恢复中…" : "恢复生成"}
          </Button>
        )}
        <span className="measure text-xs text-ink-faint">
          {isFinal
            ? "通过后剧本落库；打回则回到剧本书写重做一轮。"
            : "恢复后流水线从下一步继续。"}
        </span>
      </div>
    </section>
  );
}

function splitList(value: string): string[] {
  return value
    .split(/[、,，]/)
    .map((part) => part.trim())
    .filter(Boolean);
}

/** 素材结论编辑：背景/时代/情节/教学要点/人物笔记。 */
function DossierEditor({
  dossier,
  onChange,
}: {
  dossier: MaterialDossier;
  onChange: (next: MaterialDossier) => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      <label className="flex flex-col gap-1.5">
        <span className={LABEL}>背景</span>
        <textarea
          value={dossier.background}
          onChange={(e) => onChange({ ...dossier, background: e.target.value })}
          rows={2}
          className={`${FIELD} resize-y font-serif leading-[1.9]`}
        />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className={LABEL}>时代设定 / 世界观</span>
        <textarea
          value={dossier.era_setting}
          onChange={(e) => onChange({ ...dossier, era_setting: e.target.value })}
          rows={2}
          className={`${FIELD} resize-y font-serif leading-[1.9]`}
        />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className={LABEL}>情节概要</span>
        <textarea
          value={dossier.plot_summary}
          onChange={(e) => onChange({ ...dossier, plot_summary: e.target.value })}
          rows={3}
          className={`${FIELD} resize-y font-serif leading-[1.9]`}
        />
      </label>
      {dossier.character_notes.length > 0 && (
        <div className="flex flex-col gap-2">
          <span className={LABEL}>人物笔记</span>
          {dossier.character_notes.map((note, i) => (
            <div key={i} className="flex flex-col gap-2 rounded-md border border-rule p-2.5">
              <input
                value={note.name}
                onChange={(e) =>
                  onChange({
                    ...dossier,
                    character_notes: dossier.character_notes.map((n, j) =>
                      j === i ? { ...n, name: e.target.value } : n
                    ),
                  })
                }
                className={`${FIELD} font-serif`}
                aria-label="人物名"
                placeholder="人物名"
              />
              <textarea
                value={note.note}
                onChange={(e) =>
                  onChange({
                    ...dossier,
                    character_notes: dossier.character_notes.map((n, j) =>
                      j === i ? { ...n, note: e.target.value } : n
                    ),
                  })
                }
                rows={2}
                className={`${FIELD} resize-y`}
                aria-label="人物结论"
                placeholder="人物结论"
              />
            </div>
          ))}
        </div>
      )}
      <label className="flex flex-col gap-1.5">
        <span className={LABEL}>教学要点（每行一条）</span>
        <textarea
          value={dossier.teaching_analysis.join("\n")}
          onChange={(e) =>
            onChange({
              ...dossier,
              teaching_analysis: e.target.value
                .split("\n")
                .map((line) => line.trim())
                .filter(Boolean),
            })
          }
          rows={2}
          className={`${FIELD} resize-y`}
        />
      </label>
    </div>
  );
}

/** 网络证据只读列表（来源审计）。 */
function EvidenceList({ items }: { items: GateReview["evidence"] }) {
  return (
    <div className="flex flex-col gap-2">
      <span className={LABEL}>网络资料（{items.length} 条，只读）</span>
      {items.map((item, i) => (
        <div key={i} className="rounded-md border border-rule p-2.5 text-xs">
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="font-medium text-accent underline"
          >
            {item.title}
          </a>
          <p className="measure mt-1 text-ink-faint">{item.excerpt}</p>
        </div>
      ))}
    </div>
  );
}
