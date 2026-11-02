"use client";

import type { OriginalEvidenceRef, Scene, StageValue } from "@/lib/contracts/types";
import { Tag } from "@/components/ui/tag";

/** `scene:{id}` → 场景 id；运行期新场景（非剧本场景）返回 null。 */
export function sceneIdOf(sceneKey: string | null): number | null {
  const match = sceneKey ? /^scene:(\d+)$/.exec(sceneKey) : null;
  return match ? Number(match[1]) : null;
}

function originalRefs(scene: Scene): { description: string; refs: OriginalEvidenceRef[] }[] {
  return scene.beats.map((beat) => ({
    description: beat.description,
    refs: beat.evidence_refs.filter(
      (r): r is OriginalEvidenceRef => r.source_type === "original_text"
    ),
  }));
}

/** 这一幕在课文里有没有原文可对照（舞台上的「对照原文」入口据此显隐）。 */
export function sceneHasOriginal(scene: Scene | undefined): boolean {
  return (
    scene !== undefined &&
    scene.beats.some((b) => b.evidence_refs.some((r) => r.source_type === "original_text"))
  );
}

/**
 * 课文里已经演到的场景：一幕一节，按情节点列出剧本据以改编的原文摘录与段落号。
 *
 * **只列已经演过的场景**：还没演到的部分不提前展示，免得学生先看了答案再演。
 * 续写阶段与终局时课文已演完，全部展开。当前这一幕默认展开，之前的收起。
 */
export function OriginalTextPanel({
  scenes,
  sceneKey,
  stage,
}: {
  scenes: Scene[];
  sceneKey: string | null;
  stage: StageValue;
}) {
  const finished = stage === "stage2_complete" || stage === "stage3_extending" || stage === "ended";
  const currentId = sceneIdOf(sceneKey);
  const currentIndex = scenes.findIndex((s) => s.scene_id === currentId);
  const visible = finished ? scenes : currentIndex >= 0 ? scenes.slice(0, currentIndex + 1) : [];

  if (scenes.length === 0) {
    return <p className="py-6 text-center text-sm text-ink-faint">剧本原文还没取回来。</p>;
  }
  if (visible.length === 0) {
    return (
      <p className="py-6 text-center text-sm text-ink-faint">
        剧情开始后，这里会对照课文原文。
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {visible.map((scene) => {
        const current = scene.scene_id === currentId;
        const beats = originalRefs(scene);
        return (
          <details
            key={scene.scene_id}
            open={current || finished}
            className={`group rounded-2xl border px-3 py-2.5 ${
              current ? "border-glow-gold/40 bg-glow-gold/5" : "border-glass-edge"
            }`}
          >
            <summary className="flex cursor-pointer list-none items-center gap-2 font-serif text-base text-ink">
              <span
                aria-hidden
                className="text-xs text-ink-faint transition-transform group-open:rotate-90"
              >
                ▸
              </span>
              {scene.title}
              {current && !finished && <Tag tone="flag">正在演</Tag>}
            </summary>
            <ol className="mt-2.5 flex flex-col gap-3">
              {beats.map((beat, i) => (
                <li key={i} className="flex flex-col gap-1.5">
                  <p className="text-xs text-ink-faint">{beat.description}</p>
                  {beat.refs.map((ref, j) => (
                    <blockquote
                      key={j}
                      className="border-l-2 border-glow-gold/60 pl-3 font-serif text-sm leading-[1.9] text-ink"
                    >
                      {ref.excerpt}
                      {ref.paragraph_index !== null && (
                        <span className="ml-2 align-middle font-sans text-2xs text-glow-gold">
                          第 {ref.paragraph_index + 1} 段
                        </span>
                      )}
                    </blockquote>
                  ))}
                </li>
              ))}
            </ol>
          </details>
        );
      })}
      {!finished && currentIndex < scenes.length - 1 && (
        <p className="pb-2 text-center text-2xs text-ink-faint">
          后面的课文要演到才会出现。
        </p>
      )}
    </div>
  );
}
