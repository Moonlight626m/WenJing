import { ASSET_IMAGE_BG, AssetImage } from "@/components/asset-image";
import { Tag } from "@/components/ui/tag";
import type {
  Appearance,
  AssetCredit,
  Beat,
  ScriptPackage,
  VisualNotes,
} from "@/lib/contracts/types";
import { requiresAttribution } from "@/lib/labels";

/**
 * 署名/来源展示（#51，ADR-0005 §6 修订 Q22/Q26）：
 * - 教师端（audience="teacher"）：完整展示作者/许可/来源链接；
 * - 学生端（audience="student"）：免署名许可（CC0/PD）不展示，不破坏沉浸；
 *   需署名许可（CC BY/BY-SA）必须展示——折叠为 <details>，默认收起。
 */
function CreditSlot({
  label,
  credit,
  audience,
}: {
  label: string;
  credit: AssetCredit;
  audience: "teacher" | "student";
}) {
  if (audience === "student" && !requiresAttribution(credit.license)) {
    return null;
  }
  if (audience === "teacher") {
    return (
      <p className="mt-1 flex flex-wrap items-baseline gap-x-2 text-2xs text-ink-faint">
        <span>{label}来源</span>
        {credit.source_url ? (
          <a href={credit.source_url} target="_blank" rel="noreferrer" className="text-accent underline">
            {credit.author || "未知作者"}
          </a>
        ) : (
          <span className="text-ink-soft">{credit.author || "未知作者"}</span>
        )}
        {credit.license && <span className="font-mono">{credit.license}</span>}
        {credit.license_url && (
          <a href={credit.license_url} target="_blank" rel="noreferrer" className="text-accent underline">
            许可全文
          </a>
        )}
      </p>
    );
  }
  return (
    <details className="mt-1 text-2xs text-ink-faint">
      <summary className="cursor-pointer select-none">图片来源与许可（{label}）</summary>
      <span className="mt-1 flex flex-wrap items-baseline gap-x-2">
        <span className="text-ink-soft">{credit.author || "未知作者"}</span>
        {credit.license && <span className="font-mono">{credit.license}</span>}
        {credit.source_url && (
          <a href={credit.source_url} target="_blank" rel="noreferrer" className="text-accent underline">
            来源
          </a>
        )}
        {credit.license_url && (
          <a href={credit.license_url} target="_blank" rel="noreferrer" className="text-accent underline">
            许可全文
          </a>
        )}
      </span>
    </details>
  );
}

/** 场景卡默认只露两拍，其余折叠——详情页先给「这一幕讲什么」的简明版本。 */
const BEAT_PREVIEW = 2;

/** 视觉锚点一行（时期/地点/时段/天气/氛围），供教师核对生成图是否贴课文。 */
function VisualNotesLine({ notes }: { notes?: VisualNotes | null }) {
  if (!notes) return null;
  const parts = [
    notes.era,
    notes.location,
    notes.time_of_day,
    notes.weather,
    notes.mood,
  ].filter(Boolean);
  if (parts.length === 0) return null;
  return (
    <p className="mt-1 text-xs text-ink-faint">画面 {parts.join(" · ")}</p>
  );
}

/** 外貌锚点一行（画师层生图依据）：只给教师核对；未交代处会如实标注。 */
function AppearanceLine({ appearance }: { appearance?: Appearance | null }) {
  if (!appearance) return null;
  const parts = [
    appearance.face && `面容 ${appearance.face}`,
    appearance.hair && `发式 ${appearance.hair}`,
    appearance.clothing && `衣着 ${appearance.clothing}`,
    appearance.accessories && `配饰 ${appearance.accessories}`,
    appearance.build && `身形 ${appearance.build}`,
  ].filter(Boolean);
  if (parts.length === 0) return null;
  return (
    <p className="mt-2 text-xs text-ink-faint">
      外貌锚点 <span className="text-ink-soft">{parts.join(" · ")}</span>
    </p>
  );
}

function BeatItem({ beat }: { beat: Beat }) {
  return (
    <li>
      {beat.description}
      {beat.is_key_event && (
        <Tag tone="warn" className="ml-2 align-middle">
          关键
        </Tag>
      )}
    </li>
  );
}

/** 场景/分支节拍：默认简洁，完整节拍折叠在 details 里（教师审阅仍可展开）。 */
function BeatList({ beats }: { beats: Beat[] }) {
  const head = beats.slice(0, BEAT_PREVIEW);
  const rest = beats.slice(BEAT_PREVIEW);
  return (
    <>
      <ol className="measure mt-3 flex flex-col gap-1.5 text-sm leading-relaxed text-ink-soft">
        {head.map((beat) => (
          <BeatItem key={beat.beat_id} beat={beat} />
        ))}
      </ol>
      {rest.length > 0 && (
        <details className="mt-1.5 text-xs text-ink-faint">
          <summary className="cursor-pointer select-none">
            展开其余 {rest.length} 拍
          </summary>
          <ol className="measure mt-1.5 flex flex-col gap-1.5 text-sm leading-relaxed text-ink-soft">
            {rest.map((beat) => (
              <BeatItem key={beat.beat_id} beat={beat} />
            ))}
          </ol>
        </details>
      )}
    </>
  );
}

/** 剧本包只读预览（教师发布前核对角色/场景/关键事件）。 */
export function ScriptPreview({
  scriptPackage,
  audience = "teacher",
}: {
  scriptPackage: ScriptPackage;
  audience?: "teacher" | "student";
}) {
  return (
    <section className="flex flex-col gap-8 border-t border-rule pt-8">
      <div className="flex flex-col gap-2">
        <h2 className="text-xl text-ink">{scriptPackage.title}</h2>
        <p className="text-sm text-ink-soft">
          可扮演角色
          <span className="ml-2 text-ink">
            {scriptPackage.playable_roles.length > 0
              ? scriptPackage.playable_roles.join("、")
              : "（无）"}
          </span>
        </p>
      </div>

      {scriptPackage.teaching_focus.length > 0 && (
        <div className="flex flex-col gap-2.5">
          <h3 className="text-sm text-ink-soft">教学重点</h3>
          <ul className="flex flex-wrap gap-1.5">
            {scriptPackage.teaching_focus.map((focus) => (
              <li key={focus}>
                <Tag tone="accent">{focus}</Tag>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-col gap-3">
        <h3 className="border-b border-rule pb-2 text-sm text-ink-soft">
          角色 <span className="ml-1 font-mono text-xs text-ink-faint">{scriptPackage.characters.length}</span>
        </h3>
        <ul className="flex flex-col gap-3">
          {scriptPackage.characters.map((character) => (
            <li
              key={character.name}
              className="rounded-lg border border-rule bg-surface px-4 py-3"
            >
              <div className="flex gap-4">
                {/* 无图角色不占位（纯文本卡片），有图才撑出版面 */}
                {(character.avatar_asset || character.fullbody_asset) && (
                  <div className="flex shrink-0 flex-col gap-1.5">
                    {character.avatar_asset && (
                      <AssetImage
                        asset={character.avatar_asset}
                        alt={`${character.name} 头像`}
                        className={`h-16 w-16 rounded-sm ${ASSET_IMAGE_BG}`}
                      />
                    )}
                    {character.fullbody_asset && (
                      <AssetImage
                        asset={character.fullbody_asset}
                        alt={`${character.name} 立绘`}
                        className={`h-24 w-16 rounded-sm ${ASSET_IMAGE_BG}`}
                      />
                    )}
                  </div>
                )}
                <div className="flex min-w-0 flex-1 flex-col">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-serif text-lg text-ink">{character.name}</span>
                    {character.is_player_playable.value && (
                      <Tag tone="accent">可扮演</Tag>
                    )}
                  </div>
                  {character.avatar_credit && (
                    <CreditSlot label="头像" credit={character.avatar_credit} audience={audience} />
                  )}
                  {character.fullbody_credit && (
                    <CreditSlot label="立绘" credit={character.fullbody_credit} audience={audience} />
                  )}
                  {character.public_background && (
                    <p className="measure mt-2 text-sm text-ink-soft">
                      {character.public_background}
                    </p>
                  )}
                  {character.personality_traits.length > 0 && (
                    <p className="mt-2 text-xs text-ink-faint">
                      性格 {character.personality_traits.map((t) => t.label).join("、")}
                    </p>
                  )}
                  {audience === "teacher" && (
                    <AppearanceLine appearance={character.appearance} />
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex flex-col gap-3">
        <h3 className="border-b border-rule pb-2 text-sm text-ink-soft">
          场景与情节 <span className="ml-1 font-mono text-xs text-ink-faint">{scriptPackage.scenes.length}</span>
        </h3>
        {/* 场景本来就是有序的（scene_id 递增），编号在这里承载真实顺序 */}
        <ol className="flex flex-col gap-5">
          {scriptPackage.scenes.map((scene) => (
            <li key={scene.scene_id} className="flex gap-3">
              <span className="w-5 shrink-0 pt-4 text-right font-mono text-2xs text-ink-faint tabular-nums">
                {String(scene.scene_id).padStart(2, "0")}
              </span>
              <div className="min-w-0 flex-1 border-l border-rule pl-4">
                {/* 每个场景都有图位：缺图也要露出占位，教师才知道该补哪一场 */}
                <AssetImage
                  asset={scene.background_asset}
                  alt={`场景「${scene.title}」画面`}
                  className={`mb-3 aspect-video w-full rounded-sm ${ASSET_IMAGE_BG}`}
                  emptyLabel="本场暂无配图"
                />
                <div className="font-serif text-base text-ink">{scene.title}</div>
                {scene.participants.length > 0 && (
                  <div className="mt-0.5 text-xs text-ink-faint">
                    出场 {scene.participants.join("、")}
                  </div>
                )}
                {audience === "teacher" && (
                  <VisualNotesLine notes={scene.visual_notes} />
                )}
                {scene.background_credit && (
                  <CreditSlot label="画面" credit={scene.background_credit} audience={audience} />
                )}
                <BeatList beats={scene.beats} />
                {scene.branches && scene.branches.length > 0 && (
                  <ul className="mt-3 flex flex-col gap-2 border-l-2 border-rule pl-3">
                    {scene.branches.map((branch) => (
                      <li
                        key={branch.branch_id}
                        className="rounded-md border border-rule bg-canvas/40 p-3"
                      >
                        <div className="flex gap-3">
                          <AssetImage
                            asset={branch.background_asset}
                            alt={`分支「${branch.title}」画面`}
                            className={`aspect-video w-28 shrink-0 rounded-sm ${ASSET_IMAGE_BG}`}
                            emptyLabel="暂无配图"
                            placeholderClassName="text-2xs text-ink-faint"
                          />
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <Tag tone="accent">分支</Tag>
                              <span className="font-serif text-sm text-ink">
                                {branch.title}
                              </span>
                            </div>
                            <p className="mt-1 text-xs text-ink-soft">
                              选项：{branch.label}
                            </p>
                            {branch.participants.length > 0 && (
                              <p className="mt-0.5 text-xs text-ink-faint">
                                出场 {branch.participants.join("、")}
                              </p>
                            )}
                            {audience === "teacher" && (
                              <VisualNotesLine notes={branch.visual_notes} />
                            )}
                          </div>
                        </div>
                        <BeatList beats={branch.beats} />
                        {branch.background_credit && (
                          <CreditSlot
                            label={`分支「${branch.title}」`}
                            credit={branch.background_credit}
                            audience={audience}
                          />
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
