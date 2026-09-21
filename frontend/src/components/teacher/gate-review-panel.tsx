"use client";

import { useState } from "react";

import type {
  CharacterProfile,
  GateEdits,
  GateReview,
  MaterialDossier,
  ScriptPackage,
} from "@/lib/contracts/types";

const TEXT_FIELD =
  "w-full rounded-lg border border-amber-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-amber-500 dark:border-amber-800";
const LABEL = "text-xs font-medium text-amber-700 dark:text-amber-300";

export interface GateResumePayload {
  directives: string[];
  edits: GateEdits;
  action: "approve" | "reject";
}

const GATE_TITLES: Record<string, string> = {
  materials: "教师闸门 · 素材审阅",
  pre_write: "教师闸门 · 人物与场景审定",
  final: "教师闸门 · 剧本终审",
};

const GATE_HINTS: Record<string, string> = {
  materials:
    "素材收集与考证已通过。可直接编辑时代背景/世界观等素材结论（编辑稿直接用于下游生成），也可附加指导指令；素材区默认折叠，点“展开素材”查看与修改。",
  pre_write:
    "事件划分与人物设定已完成。可编辑场景名称、参与人物与人物形象，审定后进入剧本书写；也可附加指导指令。",
  final:
    "doubter 总审已通过。可编辑剧本标题与场景名，通过即落库；或填写打回意见退回剧本书写重做一轮。",
};

/** 教师闸门审阅面板（#34）：按闸门位置展示中间产物，支持编辑与指导。 */
export function GateReviewPanel({
  review,
  busy,
  onResume,
}: {
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
      schema_version: "2.0.0",
      dossier: null,
      division: null,
      profiles: null,
      package: null,
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
      edits: { ...empty, package: editedOr(packageDraft, review?.package ?? null) },
      action,
    };
  }

  const isFinal = gate === "final";

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/30">
      <h2 className="text-sm font-medium text-amber-700 dark:text-amber-300">
        {GATE_TITLES[gate]}
      </h2>
      <p className="text-xs text-amber-700/80 dark:text-amber-300/80">
        {GATE_HINTS[gate]}
      </p>

      {gate === "materials" && (
        <>
          <button
            type="button"
            onClick={() => setMaterialsOpen((open) => !open)}
            className="self-start rounded-lg border border-amber-300 px-3 py-1 text-xs transition-colors hover:bg-amber-100 dark:border-amber-800 dark:hover:bg-amber-900/40"
          >
            {materialsOpen ? "收起素材" : "展开素材"}
          </button>
          {materialsOpen &&
            (dossier ? (
              <DossierEditor dossier={dossier} onChange={setDossier} />
            ) : (
              <p className="text-xs text-amber-700/70 dark:text-amber-300/70">
                本次生成未提供可编辑的素材结论。
              </p>
            ))}
          {materialsOpen && review && review.evidence.length > 0 && (
            <EvidenceList items={review.evidence} />
          )}
        </>
      )}

      {gate === "pre_write" && (
        <>
          {review?.division && (
            <div className="flex flex-col gap-2">
              <span className={LABEL}>场景划分（可编辑场景名与参与人物）</span>
              {review.division.scenes.map((scene, i) => (
                <div
                  key={i}
                  className="flex flex-col gap-1 rounded-lg border border-amber-200 p-2 dark:border-amber-900"
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
                    className={TEXT_FIELD}
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
                    className={TEXT_FIELD}
                    placeholder="参与人物（用顿号或逗号分隔）"
                  />
                  <p className="text-xs text-amber-700/70 dark:text-amber-300/70">
                    {scene.beats.map((beat) => beat.description).join(" → ")}
                  </p>
                </div>
              ))}
            </div>
          )}
          {profiles.length > 0 && (
            <div className="flex flex-col gap-2">
              <span className={LABEL}>人物设定（可编辑形象与语言风格）</span>
              {profiles.map((profile, i) => (
                <div
                  key={profile.name}
                  className="flex flex-col gap-1 rounded-lg border border-amber-200 p-2 dark:border-amber-900"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{profile.name}</span>
                    <label className="flex items-center gap-1 text-xs text-amber-700 dark:text-amber-300">
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
                    className={TEXT_FIELD}
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
                    className={TEXT_FIELD}
                    placeholder="语言时代层（可选；五要素在结构化编辑中维护）"
                  />
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {isFinal && packageDraft && (
        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-1">
            <span className={LABEL}>剧本标题</span>
            <input
              value={packageDraft.title}
              onChange={(e) =>
                setPackageDraft({ ...packageDraft, title: e.target.value })
              }
              className={TEXT_FIELD}
            />
          </label>
          {packageDraft.scenes.map((scene, i) => (
            <label key={scene.scene_id} className="flex flex-col gap-1">
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
                className={TEXT_FIELD}
              />
            </label>
          ))}
        </div>
      )}

      <textarea
        value={directives}
        onChange={(e) => setDirectives(e.target.value)}
        rows={3}
        placeholder={
          isFinal
            ? "打回时的指导意见（每行一条），例如：\n结尾要落在父亲转身之后"
            : "每行一条指导指令（可选），例如：\n孔乙己的迂腐要更突出"
        }
        className={TEXT_FIELD}
      />
      <div className="flex items-center gap-3">
        {isFinal ? (
          <>
            <button
              type="button"
              onClick={() => onResume(buildResume("approve"))}
              disabled={busy !== null}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm text-white transition-opacity hover:opacity-85 disabled:opacity-50"
            >
              {busy === "resume" ? "处理中…" : "通过并落库"}
            </button>
            <button
              type="button"
              onClick={() => onResume(buildResume("reject"))}
              disabled={busy !== null}
              className="rounded-lg border border-amber-400 px-4 py-2 text-sm text-amber-700 transition-colors hover:bg-amber-100 disabled:opacity-50 dark:border-amber-700 dark:text-amber-300 dark:hover:bg-amber-900/40"
            >
              打回重写
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => onResume(buildResume("approve"))}
            disabled={busy !== null}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white transition-opacity hover:opacity-85 disabled:opacity-50"
          >
            {busy === "resume" ? "恢复中…" : "恢复生成"}
          </button>
        )}
        <span className="text-xs text-amber-700/70 dark:text-amber-300/70">
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
    <div className="flex flex-col gap-2">
      <label className="flex flex-col gap-1">
        <span className={LABEL}>背景</span>
        <textarea
          value={dossier.background}
          onChange={(e) => onChange({ ...dossier, background: e.target.value })}
          rows={2}
          className={TEXT_FIELD}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className={LABEL}>时代设定 / 世界观</span>
        <textarea
          value={dossier.era_setting}
          onChange={(e) => onChange({ ...dossier, era_setting: e.target.value })}
          rows={2}
          className={TEXT_FIELD}
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className={LABEL}>情节概要</span>
        <textarea
          value={dossier.plot_summary}
          onChange={(e) => onChange({ ...dossier, plot_summary: e.target.value })}
          rows={3}
          className={TEXT_FIELD}
        />
      </label>
      {dossier.character_notes.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className={LABEL}>人物笔记</span>
          {dossier.character_notes.map((note, i) => (
            <div key={i} className="flex flex-col gap-1 rounded-lg border border-amber-200 p-2 dark:border-amber-900">
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
                className={TEXT_FIELD}
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
                className={TEXT_FIELD}
                placeholder="人物结论"
              />
            </div>
          ))}
        </div>
      )}
      <label className="flex flex-col gap-1">
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
          className={TEXT_FIELD}
        />
      </label>
    </div>
  );
}

/** 网络证据只读列表（来源审计）。 */
function EvidenceList({ items }: { items: GateReview["evidence"] }) {
  return (
    <div className="flex flex-col gap-1">
      <span className={LABEL}>网络资料（{items.length} 条，只读）</span>
      {items.map((item, i) => (
        <div key={i} className="rounded-lg border border-amber-200 p-2 text-xs dark:border-amber-900">
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="font-medium underline"
          >
            {item.title}
          </a>
          <p className="mt-1 text-amber-700/70 dark:text-amber-300/70">{item.excerpt}</p>
        </div>
      ))}
    </div>
  );
}
