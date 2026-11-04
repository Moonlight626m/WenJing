"use client";

import { putCachedAssetUrl } from "@/lib/asset-url";
import { ALLOWED_COMMANDS } from "@/lib/contracts/types";
import type {
  CommandKind,
  PlayerCommand,
  ScriptPackage,
  Stage3Goal,
  StageValue,
} from "@/lib/contracts/types";
import type { DemoBeat, DemoChoice, DemoOption, DemoScript } from "@/lib/demo/types";
import { resetDemoStore, saveUnlocked, useDemoStore, type CaughtQuote } from "@/lib/demo/store";
import { useGameStore, type ChatMessage } from "@/stores/gameStore";

/** 预置资产的地址永不过期：它们是 public 下的静态文件，不走签名。 */
const NEVER = "2999-12-31T00:00:00Z";

/** 逐字打出的速度（毫秒/字）。 */
const TYPE_MS = 48;

/** 旁白停留：起步 1.2 秒，每字再加 0.11 秒，上限 7 秒。 */
function narrationMs(text: string): number {
  return Math.min(7000, 1200 + Array.from(text).length * 110);
}

/** 台词打完后的停留：起步 0.9 秒，每字再加 0.05 秒，上限 3.6 秒。 */
function dwellMs(text: string): number {
  return Math.min(3600, 900 + Array.from(text).length * 50);
}

/** 选完到出第一句之间的「思考」：命运抉择多留一拍给墨点溅开。 */
const THINK_MS = 650;
const FATE_THINK_MS = 1300;

/** 幕间过场（`ActCurtain`）大约演 3.4 秒，换幕后等它落下再接着演。 */
const CURTAIN_MS = 3600;

function sceneKey(sceneId: number): string {
  return `scene:${sceneId}`;
}

function backgroundId(slug: string, sceneId: number): string {
  return `demo-${slug}-bg-${sceneId}`;
}

function portraitId(slug: string, name: string): string {
  return `demo-${slug}-portrait-${encodeURIComponent(name)}`;
}

/** 回到某个抉择点时要还原的东西。 */
interface Snapshot {
  choice: DemoChoice;
  seq: number;
  flags: Record<string, string>;
  quotes: CaughtQuote[];
  game: {
    messages: ChatMessage[];
    stage: StageValue;
    sceneKey: string | null;
    sceneTitle: string | null;
    currentAsset: ReturnType<typeof useGameStore.getState>["currentAsset"];
    stage3Goals: Stage3Goal[];
  };
}

/**
 * 演出导演：照台本往 gameStore 灌消息，舞台渲染的是和真实游戏同一套组件。
 *
 * 它顶替 WS 的位置——`setSender` 换成自己的 {@link DemoDirector.send}，抉择卡、回溯栏、
 * 「进入剧情续写」发出来的命令都落到这里，由台本决定接下来演什么。消息形状与后端
 * `session_projection` 的投影一致：旁白带 `scene_key` 换场，台词先走 `stream_*` 逐字打出
 * 再落一条 `character_speech`，换阶段是一条「进入阶段：X」的系统消息。
 *
 * 节奏由字数算出来；演示者按空格跳过当前等待，暂停时只停「等待」不停打字。
 */
export class DemoDirector {
  private readonly script: DemoScript;
  private readonly sessionId: string;
  /** 每次重新开演（开局、回溯）加一，旧的播放循环看到代数变了就自己退出。 */
  private generation = 0;
  private seq = 0;
  private flags: Record<string, string> = {};
  private snapshots: Snapshot[] = [];
  private choice: { beat: DemoChoice; options: DemoOption[] } | null = null;
  private awaiting: string | null = null;
  private goals: Stage3Goal[] = [];
  private paused = false;
  /** 当前等待的「立刻结束」；没有在等时为 null。 */
  private skipper: (() => void) | null = null;
  /** 暂停期间挂起的等待：恢复时重新计时。 */
  private resumer: (() => void) | null = null;
  /** 正在逐字打出时按了跳过：把剩下的字一次打完。 */
  private rush = false;
  private disposed = false;
  private begun = false;

  constructor(script: DemoScript) {
    this.script = script;
    this.sessionId = `demo-${script.slug}-${Date.now().toString(36)}`;
  }

  /**
   * 把舞台布置好：剧本包、预置图、连上「假的」通道，停在选角之后、开演之前。
   * 可以在 dispose 之后再调一次（开发模式下 React 会把副作用跑两遍）。
   */
  boot() {
    const { script } = this;
    this.generation += 1;
    this.disposed = false;
    this.begun = false;
    this.seq = 0;
    this.flags = {};
    this.snapshots = [];
    this.choice = null;
    this.awaiting = null;
    this.goals = [];
    this.paused = false;
    this.skipper = null;
    this.resumer = null;
    resetDemoStore();
    for (const [id, url] of Object.entries(script.backgrounds)) {
      putCachedAssetUrl(backgroundId(script.slug, Number(id)), url, NEVER);
    }
    for (const [name, url] of Object.entries(script.portraits ?? {})) {
      putCachedAssetUrl(portraitId(script.slug, name), url, NEVER);
    }

    const game = useGameStore.getState();
    game.resetSession(this.sessionId);
    game.setScriptInfo(this.packageWithAssets());
    game.setSender(this.send);
    game.setConnection("connected");
    this.emit({
      type: "session_init",
      payload: {
        stage: "stage1_complete",
        player_role: null,
        plot_log: [],
        stage3_goals: [],
        active_interaction: null,
        allowed_commands: [],
      },
    });
  }

  /** 选定角色，开演。 */
  begin() {
    if (this.begun || this.disposed) return;
    this.begun = true;
    useGameStore.setState({
      playerRole: this.script.playerRole,
      selectedRole: this.script.playerRole,
    });
    this.emitPersistent("system", { text: `你将扮演：${this.script.playerRole}` });
    void this.run(this.script.start);
  }

  dispose() {
    this.disposed = true;
    this.generation += 1;
    this.release();
  }

  // ===== 演示者的遥控 =====

  /** 跳过当前等待；正在打字就一次打完。 */
  next() {
    if (this.skipper) {
      this.rush = true;
      this.skipper();
    }
  }

  setPaused(paused: boolean) {
    this.paused = paused;
    useDemoStore.setState({ paused });
    if (!paused && this.resumer) {
      const resume = this.resumer;
      this.resumer = null;
      resume();
    }
  }

  /** 平行世界：回到最近一次命运抉择，换一条路。 */
  parallel() {
    const index = this.snapshots.findLastIndex((s) => s.choice.fate);
    if (index >= 0) this.restore(index);
  }

  // ===== 「通道」：抉择卡等组件发出的命令落在这里 =====

  send = (message: unknown) => {
    if (this.disposed || typeof message !== "object" || message === null) return;
    const msg = message as { type?: string; command?: PlayerCommand };
    if (msg.type !== "submit_command" || !msg.command) return;
    void this.onCommand(msg.command);
  };

  private async onCommand(command: PlayerCommand) {
    const kind = command.kind as CommandKind;
    const payload = (command.payload ?? {}) as Record<string, unknown>;

    if (kind === "choose_option" && this.choice) {
      const index = Number(String(payload.option_id ?? "").replace(/^o/, "")) - 1;
      const option = this.choice.options[index];
      if (option) return this.choose(option);
    }
    if (kind === "free_input" && this.choice?.beat.free) {
      return this.write(String(payload.text ?? ""));
    }
    if (kind === "rollback_to_event") {
      const target = Number(payload.target_sequence);
      const index = this.snapshots.findLastIndex((s) => s.seq <= target);
      return this.restore(Math.max(0, index), target);
    }
    if (kind === "enter_stage3" && this.awaiting) {
      const next = this.awaiting;
      this.awaiting = null;
      return this.run(next);
    }
    if (kind === "confirm_ending" || kind === "exit_game") {
      this.choice = null;
      this.awaiting = null;
      return this.run(this.script.finale);
    }
    // 台本里没有对应的去处：放掉等待态，别让顶栏一直转
    useGameStore.setState({ pending: null });
  }

  /** 选了一个选项。 */
  private async choose(option: DemoOption) {
    const current = this.choice;
    if (!current) return;
    this.choice = null;
    Object.assign(this.flags, option.set ?? {});
    useDemoStore.setState({ flags: { ...this.flags }, suggestions: [] });
    const gen = ++this.generation;
    const fate = current.beat.fate === true;
    if (fate) useDemoStore.setState({ fate: "splash" });

    await this.sleep(fate ? FATE_THINK_MS : THINK_MS);
    if (gen !== this.generation) return;
    this.settle();
    if (fate) useDemoStore.setState({ fate: "idle" });

    // 先做后说：「把画册塞进他手里」，再「这个给你」
    if (option.act) await this.play({ t: "narrate", text: option.act }, gen);
    if (gen !== this.generation) return;
    if (option.say) await this.speak(this.script.playerRole, option.say, gen);
    if (gen !== this.generation) return;
    void this.run(option.next, gen);
  }

  /** 自己写了一句。按关键词接到台本里最贴近的那一支。 */
  private async write(text: string) {
    const current = this.choice;
    const free = current?.beat.free;
    if (!current || !free) return;
    this.choice = null;
    useDemoStore.setState({ suggestions: [] });
    const gen = ++this.generation;
    this.settle();

    await this.speak(this.script.playerRole, text, gen);
    if (gen !== this.generation) return;
    // 命中关键词最多的那一支；一样多时取靠前的
    let route: (typeof free.routes)[number] | undefined;
    let best = 0;
    for (const r of free.routes) {
      if (r.hideIf && this.flags[r.hideIf]) continue;
      const hits = r.keywords.filter((k) => text.includes(k)).length;
      if (hits > best) {
        route = r;
        best = hits;
      }
    }
    void this.run(route?.next ?? free.fallback, gen);
  }

  // ===== 播放 =====

  private async run(nodeId: string, gen = ++this.generation) {
    let id = nodeId;
    let i = 0;
    while (gen === this.generation) {
      const beats = this.script.nodes[id];
      if (!beats || i >= beats.length) return;
      const beat = beats[i];
      i += 1;
      switch (beat.t) {
        case "goto":
          id = beat.to;
          i = 0;
          continue;
        case "switch":
          id = beat.cases[this.flags[beat.key] ?? ""] ?? beat.fallback;
          i = 0;
          continue;
        case "when":
          if (beat.all.every((flag) => this.flags[flag])) {
            id = beat.to;
            i = 0;
          }
          continue;
        case "choice":
          this.present(beat);
          return;
        case "await":
          this.awaiting = beat.next;
          return;
        case "end":
          this.finish(beat.ending);
          return;
        default:
          await this.play(beat, gen);
      }
    }
  }

  private async play(beat: DemoBeat, gen: number) {
    switch (beat.t) {
      case "narrate": {
        const payload: Record<string, unknown> = { text: beat.text };
        if (beat.scene !== undefined) {
          const scene = this.script.package.scenes.find((s) => s.scene_id === beat.scene);
          payload.scene_key = sceneKey(beat.scene);
          payload.scene_title = scene?.title ?? null;
          if (this.script.backgrounds[beat.scene]) {
            payload.current_asset = {
              asset_id: backgroundId(this.script.slug, beat.scene),
              kind: "background",
              status: "ready",
            };
          }
        }
        this.emitPersistent("narrative", payload);
        await this.sleep(narrationMs(beat.text) + (beat.scene !== undefined ? 1200 : 0));
        return;
      }
      case "say":
        await this.speak(beat.who, beat.text, gen);
        return;
      case "system":
        this.emitPersistent("system", { text: beat.text });
        await this.sleep(300);
        return;
      case "stage": {
        this.emitPersistent("system", { text: `进入阶段：${beat.stage}` });
        // 演戏的时候抉择卡位置空着：阶段表里的「确认结局 / 退出游戏」不在这时露出来，
        // 只留回溯（剧情回顾里的回溯栏靠它显示）。停在阶段之间时照契约表来。
        if (beat.stage === "stage2_reenacting" || beat.stage === "stage3_extending") {
          useGameStore.setState({ allowedCommands: ["rollback_to_event"] });
          await this.sleep(CURTAIN_MS);
        }
        return;
      }
      case "quote":
        this.catchQuote({ text: beat.text, note: beat.note });
        await this.sleep(2600);
        return;
      case "goals":
        this.goals = beat.goals.map((description, i) => ({
          goal_id: i + 1,
          description,
          achieved: false,
        }));
        this.emitPersistent("system", {
          text: `续写目标：${beat.goals.join("；")}`,
          stage3_goals: this.goals,
        });
        await this.sleep(1600);
        return;
      case "achieve": {
        const goal = this.goals.find((g) => g.goal_id === beat.goal);
        if (!goal || goal.achieved) return;
        this.goals = this.goals.map((g) =>
          g.goal_id === beat.goal ? { ...g, achieved: true } : g
        );
        this.flags[`goal${beat.goal}`] = "1";
        useDemoStore.setState({ flags: { ...this.flags } });
        this.emitPersistent("system", {
          text: `达成续写目标：${goal.description}`,
          stage3_goals: this.goals,
        });
        await this.sleep(1600);
        return;
      }
      case "wait":
        await this.sleep(beat.ms);
        return;
      default:
        return;
    }
  }

  /** 逐字打出一句台词：先走流式字幕，打完落一条持久台词（和真实后端同一个终态规则）。 */
  private async speak(who: string, text: string, gen: number) {
    const streamId = `demo-${this.seq + 1}-${Math.random().toString(36).slice(2, 8)}`;
    this.emit({ type: "stream_start", payload: { stream_id: streamId, speaker: who } });
    this.rush = false;
    const chars = Array.from(text);
    let i = 0;
    while (i < chars.length) {
      if (gen !== this.generation) return;
      if (this.rush) {
        this.emit({
          type: "stream_delta",
          payload: { stream_id: streamId, text: chars.slice(i).join("") },
        });
        break;
      }
      this.emit({ type: "stream_delta", payload: { stream_id: streamId, text: chars[i] } });
      i += 1;
      await this.tick(TYPE_MS);
    }
    this.rush = false;
    this.emit({ type: "stream_end", payload: { stream_id: streamId } });
    this.emitPersistent("character_speech", { speaker: who, text });
    await this.sleep(dwellMs(text));
  }

  /** 停在抉择上，等演示者选。 */
  private present(beat: DemoChoice) {
    const options = beat.options.filter((o) => !(o.hideIf && this.flags[o.hideIf]));
    const game = useGameStore.getState();
    this.snapshots.push({
      choice: beat,
      seq: this.seq,
      flags: { ...this.flags },
      quotes: [...useDemoStore.getState().quotes],
      game: {
        messages: game.messages,
        stage: game.stage,
        sceneKey: game.sceneKey,
        sceneTitle: game.sceneTitle,
        currentAsset: game.currentAsset,
        stage3Goals: game.stage3Goals,
      },
    });
    this.choice = { beat, options };

    // 选项卡上只放这一刻能做的：能选、能回溯；允许自己写时才开输入框
    const allowed = ALLOWED_COMMANDS[game.stage].filter(
      (k) =>
        k !== "exit_game" && k !== "confirm_ending" && (beat.free ? true : k !== "free_input")
    );
    const mode = beat.free
      ? options.length > 0
        ? "options_with_fallback"
        : "free_input"
      : "options";
    this.emit({
      type: "interaction",
      seq: this.seq,
      payload: {
        interaction: {
          interaction_id: `${beat.id}:${this.seq}:${this.snapshots.length}`,
          mode,
          prompt: beat.prompt,
          hint: beat.hint ?? "",
          options: options.map((o, i) => ({
            option_id: `o${i + 1}`,
            label: o.label,
            proposed_by: o.proposedBy ?? null,
          })),
        },
        allowed_commands: allowed,
      },
    });
    useDemoStore.setState({
      fate: beat.fate ? "choosing" : "idle",
      suggestions: (beat.free?.suggestions ?? [])
        .filter((s) => !(s.hideIf && this.flags[s.hideIf]))
        .map((s) => s.text),
      canParallel: this.snapshots.some((s) => s.choice.fate),
    });
  }

  /** 回到第 `index` 个抉择点：消息流截到那一刻，再把那张抉择卡摆出来。 */
  private restore(index: number, target?: number) {
    const snap = this.snapshots[index];
    if (!snap) return;
    this.generation += 1;
    this.release();
    this.snapshots = this.snapshots.slice(0, index);
    this.flags = { ...snap.flags };
    this.choice = null;
    this.awaiting = null;
    this.goals = snap.game.stage3Goals;
    useGameStore.setState({
      ...snap.game,
      streams: [],
      interaction: null,
      pending: null,
    });
    const demo = useDemoStore.getState();
    useDemoStore.setState({
      quotes: snap.quotes,
      catching: null,
      ending: null,
      fate: "idle",
      rollbacks: demo.rollbacks + 1,
      flags: { ...this.flags },
    });
    this.emitPersistent("system", {
      text: `已回溯到事件 #${target ?? snap.seq}`,
      stage3_goals: snap.game.stage3Goals,
    });
    this.present(snap.choice);
  }

  private finish(ending: string) {
    this.emitPersistent("system", { text: `进入阶段：ended` });
    useDemoStore.setState({ ending, fate: "idle", suggestions: [] });
    saveUnlocked(this.script.slug, ending);
  }

  private catchQuote(quote: CaughtQuote) {
    const { quotes } = useDemoStore.getState();
    const fresh = !quotes.some((q) => q.text === quote.text);
    useDemoStore.setState({
      catching: quote,
      quotes: fresh ? [...quotes, quote] : quotes,
    });
  }

  // ===== 小工具 =====

  private packageWithAssets(): ScriptPackage {
    const { script } = this;
    return {
      ...script.package,
      characters: script.package.characters.map((c) =>
        script.portraits?.[c.name]
          ? {
              ...c,
              fullbody_asset: {
                asset_id: portraitId(script.slug, c.name),
                kind: "fullbody",
                status: "ready",
              },
            }
          : c
      ),
      scenes: script.package.scenes.map((s) =>
        script.backgrounds[s.scene_id]
          ? {
              ...s,
              background_asset: {
                asset_id: backgroundId(script.slug, s.scene_id),
                kind: "background",
                status: "ready",
              },
            }
          : s
      ),
    };
  }

  private emit(message: { type: string; seq?: number; payload: Record<string, unknown> }) {
    if (this.disposed) return;
    useGameStore.getState().handleServerMessage({ ...message, session_id: this.sessionId });
  }

  private emitPersistent(type: string, payload: Record<string, unknown>) {
    this.seq += 1;
    this.emit({ type, seq: this.seq, payload });
  }

  /** 命令有了回应：放掉等待态，收起旧的抉择卡。 */
  private settle() {
    useGameStore.setState({
      pending: null,
      interaction: null,
      allowedCommands: ["rollback_to_event"],
    });
  }

  /** 可跳过、可暂停的等待。 */
  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => {
      let timer: ReturnType<typeof setTimeout> | null = null;
      const done = () => {
        if (timer !== null) clearTimeout(timer);
        timer = null;
        if (this.skipper === done) this.skipper = null;
        this.resumer = null;
        resolve();
      };
      const arm = () => {
        timer = setTimeout(done, ms);
      };
      this.skipper = done;
      if (this.paused) this.resumer = arm;
      else arm();
    });
  }

  /** 打字的间隔：不受暂停影响，跳过时由 `rush` 一次打完。 */
  private tick(ms: number): Promise<void> {
    return new Promise((resolve) => {
      const timer = setTimeout(done, ms);
      const skip = () => {
        this.rush = true;
        done();
      };
      function done() {
        clearTimeout(timer);
        resolve();
      }
      this.skipper = skip;
    });
  }

  /** 放掉手上所有等待，让旧的播放循环走到代数检查处退出。 */
  private release() {
    const skip = this.skipper;
    this.skipper = null;
    this.resumer = null;
    skip?.();
    useDemoStore.setState({ catching: null });
  }
}
