import { ASSET_IMAGE_BG, AssetImage } from "@/components/asset-image";
import { Tag } from "@/components/ui/tag";
import type { AssetCredit, ScriptPackage } from "@/lib/contracts/types";
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
                {scene.background_asset && (
                  <AssetImage
                    asset={scene.background_asset}
                    alt={`场景「${scene.title}」背景`}
                    className={`mb-3 aspect-video w-full rounded-sm ${ASSET_IMAGE_BG}`}
                  />
                )}
                <div className="font-serif text-base text-ink">{scene.title}</div>
                {scene.participants.length > 0 && (
                  <div className="mt-0.5 text-xs text-ink-faint">
                    出场 {scene.participants.join("、")}
                  </div>
                )}
                {scene.background_credit && (
                  <CreditSlot label="背景" credit={scene.background_credit} audience={audience} />
                )}
                <ol className="measure mt-3 flex flex-col gap-1.5 text-sm leading-relaxed text-ink-soft">
                  {scene.beats.map((beat) => (
                    <li key={beat.beat_id}>
                      {beat.description}
                      {beat.is_key_event && (
                        <Tag tone="warn" className="ml-2 align-middle">
                          关键
                        </Tag>
                      )}
                    </li>
                  ))}
                </ol>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
