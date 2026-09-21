import type { ScriptPackage } from "@/lib/contracts/types";

/** 剧本包只读预览（教师发布前核对角色/场景/关键事件）。 */
export function ScriptPreview({ scriptPackage }: { scriptPackage: ScriptPackage }) {
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
              <div className="flex items-center gap-2">
                <span className="font-medium">{character.name}</span>
                {character.is_player_playable.value && (
                  <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300">
                    可扮演
                  </span>
                )}
              </div>
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
              <div className="font-medium">{scene.title}</div>
              {scene.participants.length > 0 && (
                <div className="mt-0.5 text-xs text-zinc-400">
                  出场：{scene.participants.join("、")}
                </div>
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
