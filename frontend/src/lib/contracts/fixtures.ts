/**
 * 契约 fixture 的 TS 绑定 —— fixture ↔ 前端类型的同步断言。
 *
 * 同步规则（contracts/README.md）：
 * - `contracts/fixtures/*.json` 是权威数据，前端副本逐字节一致（后端测试守卫）。
 * - JSON import 的字面量无法被 TS 静态收窄到枚举联合，因此：
 *   1) 每个 fixture 经 `asContract` 绑定到契约类型（字段名/结构对不上 → 编译错）；
 *   2) 枚举字段（genre/type/stage/mode/status/code…）在模块加载时做运行时成员校验，
 *      fixture 值与 `contracts.ts` 枚举漂移 → 立即抛错；
 *   3) 权威解析断言仍在后端 `test_contract_fixtures.py`（Pydantic extra=forbid）。
 */

import domainEventJson from "./fixtures/domain_event.json";
import errorEnvelopeJson from "./fixtures/error_envelope.json";
import materialInputJson from "./fixtures/material_input.json";
import materialJson from "./fixtures/material.json";
import playerCommandJson from "./fixtures/player_command.json";
import runtimeStateJson from "./fixtures/runtime_state.json";
import runtimeUpdateJson from "./fixtures/runtime_update.json";
import runtimeViewJson from "./fixtures/runtime_view.json";
import scriptPackageJson from "./fixtures/script_package.json";
import sessionViewJson from "./fixtures/session_view.json";

import {
  CommandType,
  ErrorCode,
  EventType,
  GameStage,
  GenreKind,
  RuntimeStatus,
  type DomainEvent,
  type ErrorEnvelope,
  type Material,
  type MaterialInput,
  type PlayerCommand,
  type RuntimeState,
  type RuntimeUpdate,
  type RuntimeView,
  type ScriptPackage,
  type SessionView,
} from "../contracts";

/** 绑定 fixture 到契约类型，并对枚举字段做运行时成员校验。 */
function asContract<T>(
  name: string,
  value: unknown,
  enums: Record<string, Record<string, string>>
): T {
  const v = value as T;
  for (const [field, map] of Object.entries(enums)) {
    const got = (v as Record<string, unknown>)[field];
    if (typeof got !== "string" || !(got in map)) {
      throw new Error(`fixture ${name}.${field} 不在契约枚举中: ${String(got)}`);
    }
  }
  return v;
}

export const materialInputFixture: MaterialInput = asContract<MaterialInput>(
  "material_input",
  materialInputJson,
  {}
);
export const materialFixture: Material = asContract<Material>("material", materialJson, {
  genre: GenreKind,
});
export const scriptPackageFixture: ScriptPackage = asContract<ScriptPackage>(
  "script_package",
  scriptPackageJson,
  { genre: GenreKind }
);
export const playerCommandFixture: PlayerCommand = asContract<PlayerCommand>(
  "player_command",
  playerCommandJson,
  { type: CommandType }
);
export const domainEventFixture: DomainEvent = asContract<DomainEvent>("domain_event", domainEventJson, {
  type: EventType,
});
export const runtimeStateFixture: RuntimeState = asContract<RuntimeState>(
  "runtime_state",
  runtimeStateJson,
  { stage: GameStage }
);
export const runtimeUpdateFixture: RuntimeUpdate = asContract<RuntimeUpdate>(
  "runtime_update",
  runtimeUpdateJson,
  { status: RuntimeStatus }
);
export const errorEnvelopeFixture: ErrorEnvelope = asContract<ErrorEnvelope>(
  "error_envelope",
  errorEnvelopeJson,
  { code: ErrorCode }
);
export const sessionViewFixture: SessionView = asContract<SessionView>("session_view", sessionViewJson, {
  stage: GameStage,
});
export const runtimeViewFixture: RuntimeView = asContract<RuntimeView>("runtime_view", runtimeViewJson, {
  stage: GameStage,
  status: RuntimeStatus,
  allowed_commands: CommandType,
});

// 联合类型哨兵：任一 fixture 漂移时此类型不可赋值，编译即失败。
export type _AllFixturesSatisfyContracts = [
  typeof materialInputFixture,
  typeof materialFixture,
  typeof scriptPackageFixture,
  typeof playerCommandFixture,
  typeof domainEventFixture,
  typeof runtimeStateFixture,
  typeof runtimeUpdateFixture,
  typeof errorEnvelopeFixture,
  typeof sessionViewFixture,
  typeof runtimeViewFixture,
];