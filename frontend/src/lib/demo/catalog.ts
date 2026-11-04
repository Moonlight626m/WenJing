import { HONGMEN } from "@/lib/demo/scripts/hongmen";
import { RUNTU } from "@/lib/demo/scripts/runtu";
import type { DemoScript, DemoSealKind } from "@/lib/demo/types";
import type { Stage3Goal } from "@/lib/contracts/types";

/** 书匣里的一卷：能演的带着台本，还在做的只有卷面。 */
export interface ShelfScroll {
  slug: string;
  title: string;
  grade: string;
  source: string;
  minutes: number;
  blurb: string;
  cover: string | null;
  roles: string[];
  endings: number;
  script: DemoScript | null;
}

function scroll(script: DemoScript): ShelfScroll {
  return {
    slug: script.slug,
    title: script.package.title,
    ...script.shelf,
    roles: [script.playerRole],
    endings: script.endings.length,
    script,
  };
}

export const SHELF: ShelfScroll[] = [scroll(RUNTU), scroll(HONGMEN)];

export function findScript(slug: string): DemoScript | null {
  return SHELF.find((s) => s.slug === slug)?.script ?? null;
}

/** 一局结束时盖上哪些印。 */
export function earnedSeals(
  script: DemoScript,
  state: {
    flags: Record<string, string>;
    rollbacks: number;
    quotes: number;
    goals: Stage3Goal[];
  }
): Set<DemoSealKind> {
  const earned = new Set<DemoSealKind>(["restore"]);
  if (state.goals.length > 0 && state.goals.every((g) => g.achieved)) earned.add("bond");
  if (state.flags.fate && state.flags.fate !== "origin") earned.add("rewrite");
  if (state.rollbacks > 0) earned.add("parallel");
  if (state.quotes >= script.quoteTotal) earned.add("collect");
  return earned;
}
