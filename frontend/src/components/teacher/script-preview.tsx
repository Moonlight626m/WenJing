import { ASSET_IMAGE_BG, AssetImage } from "@/components/asset-image";
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
      <p className="mt-1 text-[11px] text-zinc-500 dark:text-zinc-400">
        {label}来源：
        {credit.source_url ? (
          <a
            href={credit.source_url}
            target="_blank"
            rel="noreferrer"
            className="underline"
          >
            {credit.author || "未知作者"}
          </a>
        ) : (
          credit.author || "未知作者"
        )}
        {credit.license && <> · {credit.license}</>}
        {credit.license_url && (
          <>
            {" "}
            <a
              href={credit.license_url}
              target="_blank"
              rel="noreferrer"
              className="underline"
            >
              许可全文
            </a>
          </>
        )}
      </p>
    );
  }
  return (
    <details className="mt-1 text-[11px] text-zinc-400 dark:text-zinc-500">
      <summary className="cursor-pointer select-none">
        图片来源与许可（{label}）
      </summary>
      <span className="text-zinc-500 dark:text-zinc-400">
        {credit.author || "未知作者"}
        {credit.license && <> · {credit.license}</>}
        {credit.source_url && (
          <>
            {" "}
            <a
              href={credit.source_url}
              target="_blank"
              rel="noreferrer"
              className="underline"
            >
              来源
            </a>
          </>
        )}
        {credit.license_url && (
          <>
            {" "}
            <a
              href={credit.license_url}
              target="_blank"
              rel="noreferrer"
              className="underline"
            >
              许可全文
            </a>
          </>
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
    <section className="flex flex-col gap-6">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold">{scriptPackage.title}</h2>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          可扮演角色：
          {scriptPackage.playable_roles.length > 0
            ? scriptPackage.playable_roles.join("、")
            : "（无）"}
        </p>
      </div>

      {scriptPackage.teaching_focus.length > 0 && (
        <div>
          <h3 className="mb-2 text-xs font-medium text-zinc-400">教学重点</h3>
          <ul className="flex flex-wrap gap-2">
            {scriptPackage.teaching_focus.map((focus) => (
              <li
                key={focus}
                className="rounded-full bg-blue-50 px-3 py-1 text-xs text-blue-700 dark:bg-blue-950/40 dark:text-blue-300"
              >
                {focus}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <h3 className="mb-2 text-xs font-medium text-zinc-400">
          角色（{scriptPackage.characters.length}）
        </h3>
        <ul className="flex flex-col gap-2">
          {scriptPackage.characters.map((character) => (
            <li
              key={character.name}
              className="rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-800 dark:bg-zinc-900"
            >
              <div className="flex gap-3">
                {/* 无图角色不占位（纯文本卡片），有图才撑出版面 */}
                {(character.avatar_asset || character.fullbody_asset) && (
                  <div className="flex shrink-0 flex-col gap-1">
                    {character.avatar_asset && (
                      <AssetImage
                        asset={character.avatar_asset}
                        alt={`${character.name} 头像`}
                        className={`h-16 w-16 rounded-full ${ASSET_IMAGE_BG}`}
                      />
                    )}
                    {character.fullbody_asset && (
                      <AssetImage
                        asset={character.fullbody_asset}
                        alt={`${character.name} 立绘`}
                        className={`h-24 w-16 rounded ${ASSET_IMAGE_BG}`}
                      />
                    )}
                  </div>
                )}
                <div className="flex flex-1 flex-col">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{character.name}</span>
                    {character.is_player_playable.value && (
                      <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300">
                        可扮演
                      </span>
                    )}
                  </div>
                  {character.avatar_credit && (
                    <CreditSlot label="头像" credit={character.avatar_credit} audience={audience} />
                  )}
                  {character.fullbody_credit && (
                    <CreditSlot label="立绘" credit={character.fullbody_credit} audience={audience} />
                  )}
                  {character.public_background && (
                    <p className="mt-1 text-xs text-zinc-600 dark:text-zinc-400">
                      {character.public_background}
                    </p>
                  )}
                  {character.personality_traits.length > 0 && (
                    <p className="mt-1 text-xs text-zinc-400">
                      性格：{character.personality_traits.map((t) => t.label).join("、")}
                    </p>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div>
        <h3 className="mb-2 text-xs font-medium text-zinc-400">
          场景与情节（{scriptPackage.scenes.length}）
        </h3>
        <ol className="flex flex-col gap-3">
          {scriptPackage.scenes.map((scene) => (
            <li
              key={scene.scene_id}
              className="rounded-lg border border-zinc-200 bg-white p-3 text-sm dark:border-zinc-800 dark:bg-zinc-900"
            >
              {scene.background_asset && (
                <AssetImage
                  asset={scene.background_asset}
                  alt={`场景「${scene.title}」背景`}
                  className={`mb-2 aspect-video w-full rounded ${ASSET_IMAGE_BG}`}
                />
              )}
              <div className="font-medium">{scene.title}</div>
              {scene.participants.length > 0 && (
                <div className="mt-0.5 text-xs text-zinc-400">
                  出场：{scene.participants.join("、")}
                </div>
              )}
              {scene.background_credit && (
                <CreditSlot label="背景" credit={scene.background_credit} audience={audience} />
              )}
              <ol className="mt-2 flex flex-col gap-1 text-xs text-zinc-600 dark:text-zinc-400">
                {scene.beats.map((beat) => (
                  <li key={beat.beat_id} className="flex gap-2">
                    <span className="text-zinc-300 dark:text-zinc-600">·</span>
                    <span>
                      {beat.description}
                      {beat.is_key_event && (
                        <span className="ml-1 text-amber-600 dark:text-amber-400">
                          [关键]
                        </span>
                      )}
                    </span>
                  </li>
                ))}
              </ol>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
