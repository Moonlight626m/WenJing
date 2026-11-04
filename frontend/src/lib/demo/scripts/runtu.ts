/**
 * 演出台本《少年闰土》（鲁迅《故乡》节选，作品已进入公有领域）。
 *
 * 还原五场：正月初见 → 雪地捕鸟 → 月下刺猹 → 四角的天空 → 正月离别；离别是命运抉择，
 * 三个选项分别通向三个结局。续写一场：二十年后重逢，闰土那一声「老爷」之后，
 * 由你改写，三个续写目标全部达成后收束到结局。
 *
 * 台词以原文为准，原文没有的部分照人物的说话方式补写；「我」的原话一律放进旁白，
 * 你演的角色只说你自己选的、写的话——和真实游戏一样。
 */
import { CONTRACTS_SCHEMA_VERSION as V } from "@/lib/contracts/types";
import type { EvidenceRef } from "@/lib/contracts/types";
import type { DemoScript } from "@/lib/demo/types";

/** 原文证据：只标段落与摘句（段落号是本选段内的序号，从 0 起）。 */
function ref(paragraph: number, excerpt: string): EvidenceRef {
  return {
    source_type: "original_text",
    excerpt,
    paragraph_index: paragraph,
    char_start: 0,
    char_end: excerpt.length,
  };
}

const ROLE = "我";

export const RUNTU: DemoScript = {
  slug: "runtu",
  shelf: {
    grade: "初中 · 九年级上",
    source: "鲁迅《故乡》节选",
    minutes: 8,
    blurb:
      "月下的西瓜地，雪地里的竹匾，高墙上四角的天空。回到那个正月，和闰土再做一回朋友，然后改写二十年后的那一声「老爷」。",
    cover: "/demo/runtu/bg-moon.svg",
  },
  playerRole: ROLE,
  backgrounds: {
    1: "/demo/runtu/bg-newyear.svg",
    2: "/demo/runtu/bg-snow.svg",
    3: "/demo/runtu/bg-moon.svg",
    4: "/demo/runtu/bg-sky.svg",
    5: "/demo/runtu/bg-farewell.svg",
    6: "/demo/runtu/bg-return.svg",
  },
  castNotes: {
    我: "你来演。课文的叙述者，周家的少爷。",
    闰土: "AI 来演。会装弶捉鸟、月下刺猹的海边少年。",
    母亲: "AI 来演。",
    忙月: "AI 来演。闰土的父亲。",
    水生: "AI 来演。第二幕登场。",
    宏儿: "AI 来演。第二幕登场。",
  },
  quoteTotal: 6,
  package: {
    schema_version: V,
    title: "少年闰土",
    teaching_focus: [
      "品味人物的外貌与语言描写",
      "体会「我」与闰土的童年友谊",
      "理解「厚障壁」背后的隔膜",
    ],
    playable_roles: ["我", "闰土"],
    stage2_ending_beat_id: 12,
    characters: [
      {
        name: "我",
        public_background:
          "周家的少爷，十一二岁。那年家里轮到大祭祀的值年，因此认识了来管祭器的闰土。平日只看得见院子里高墙上四角的天空。",
        personality_traits: [
          { label: "好奇", evidence: "我素不知道天下有这许多新鲜事", behavior: "听见新鲜事就追着问" },
          { label: "重情", evidence: "我急得大哭", behavior: "舍不得朋友走" },
        ],
        speech_style: null,
        knowledge_boundary: { knows: ["城里的见闻", "家中的规矩"], not_knows: ["海边的生活", "猹是什么"] },
        is_player_playable: { value: true, reason: "叙述者视角，代入感强" },
      },
      {
        name: "闰土",
        public_background:
          "忙月的儿子，和「我」仿佛年纪，闰月生的，五行缺土。紫色的圆脸，头戴小毡帽，颈上套一个明晃晃的银项圈。会装弶捉鸟雀，夏夜在海边沙地上管西瓜。",
        personality_traits: [
          { label: "见多识广", evidence: "闰土的心里有无穷无尽的希奇的事", behavior: "说起海边就停不下来" },
          { label: "怕羞", evidence: "他见人很怕羞，只是不怕我", behavior: "生人面前躲在父亲身后" },
          { label: "机敏", evidence: "向一匹猹尽力的刺去", behavior: "先动手，再解释" },
        ],
        speech_style: null,
        knowledge_boundary: { knows: ["捕鸟", "看瓜", "海边的贝壳", "跳鱼儿"], not_knows: ["读书", "城里的规矩"] },
        is_player_playable: { value: true, reason: "课文的核心形象" },
      },
      {
        name: "母亲",
        public_background: "家中主母。是她告诉「我」闰土来了；二十年后，也是她催「我」去见闰土。",
        personality_traits: [{ label: "和善", evidence: "你们先前不是哥弟称呼么", behavior: "替两个孩子打圆场" }],
        speech_style: null,
        knowledge_boundary: { knows: ["家中事务"], not_knows: ["海边的活计"] },
        is_player_playable: { value: false, reason: "戏份较少" },
      },
      {
        name: "忙月",
        public_background:
          "闰土的父亲，在周家做忙月：自己也种地，只在过年过节和收租时来帮工。是他向主人家荐了儿子来管祭器。",
        personality_traits: [{ label: "疼儿子", evidence: "怕他死去，所以在神佛面前许下愿心", behavior: "嘴上严，心里软" }],
        speech_style: null,
        knowledge_boundary: { knows: ["种地", "帮工"], not_knows: ["读书"] },
        is_player_playable: { value: false, reason: "戏份较少" },
      },
      {
        name: "水生",
        public_background: "闰土的第五个孩子。黄瘦，颈上没有银圈，活脱是二十年前的闰土。",
        personality_traits: [{ label: "怕羞", evidence: "躲在他背后", behavior: "只露出半个头" }],
        speech_style: null,
        knowledge_boundary: { knows: ["海边", "跳鱼儿"], not_knows: ["城里"] },
        is_player_playable: { value: false, reason: "续写中登场" },
      },
      {
        name: "宏儿",
        public_background: "「我」的侄儿，八岁，跟着「我」回故乡搬家。",
        personality_traits: [{ label: "活泼", evidence: "宏儿听得这话，便来招水生", behavior: "见了同龄人就要拉去玩" }],
        speech_style: null,
        knowledge_boundary: { knows: ["城里"], not_knows: ["海边"] },
        is_player_playable: { value: false, reason: "续写中登场" },
      },
    ],
    scenes: [
      {
        scene_id: 1,
        title: "正月初见",
        participants: ["我", "闰土", "母亲", "忙月"],
        beats: [
          {
            beat_id: 1,
            description: "那年家里是大祭祀的值年，忙月荐了儿子闰土来管祭器。",
            is_key_event: false,
            evidence_refs: [ref(1, "那一年，我家是一件大祭祀的值年……他便对父亲说，可以叫他的儿子闰土来管祭器的。")],
          },
          {
            beat_id: 2,
            description: "闰土来了：紫色的圆脸，小毡帽，明晃晃的银项圈。",
            is_key_event: true,
            evidence_refs: [ref(3, "他正在厨房里，紫色的圆脸，头戴一顶小毡帽，颈上套一个明晃晃的银项圈")],
          },
          {
            beat_id: 3,
            description: "他见人怕羞，只是不怕我，不到半日便熟识了。",
            is_key_event: false,
            evidence_refs: [ref(3, "他见人很怕羞，只是不怕我，没有旁人的时候，便和我说话，于是不到半日，我们便熟识了。")],
          },
        ],
      },
      {
        scene_id: 2,
        title: "雪地捕鸟",
        participants: ["我", "闰土"],
        beats: [
          {
            beat_id: 4,
            description: "我要他捕鸟，他说须大雪下了才好，讲起竹匾捕鸟的法子。",
            is_key_event: true,
            evidence_refs: [ref(4, "这不能。须大雪下了才好。我们沙地上，下了雪，我扫出一块空地来，用短棒支起一个大竹匾，撒下秕谷")],
          },
          {
            beat_id: 5,
            description: "我于是又很盼望下雪。",
            is_key_event: false,
            evidence_refs: [ref(5, "我于是又很盼望下雪。")],
          },
        ],
      },
      {
        scene_id: 3,
        title: "月下刺猹",
        participants: ["我", "闰土"],
        beats: [
          {
            beat_id: 6,
            description: "闰土邀我夏天去海边，捡贝壳、管西瓜。",
            is_key_event: false,
            evidence_refs: [ref(6, "我们日里到海边捡贝壳去，红的绿的都有，鬼见怕也有，观音手也有。晚上我和爹管西瓜去，你也去。")],
          },
          {
            beat_id: 7,
            description: "月下的沙地上，少年向一匹猹尽力的刺去。",
            is_key_event: true,
            evidence_refs: [ref(0, "深蓝的天空中挂着一轮金黄的圆月，下面是海边的沙地，都种着一望无际的碧绿的西瓜")],
          },
          {
            beat_id: 8,
            description: "猹很伶俐，倒向你奔来，反从胯下窜了。",
            is_key_event: false,
            evidence_refs: [ref(8, "有胡叉呢。走到了，看见猹了，你便刺。这畜生很伶俐，倒向你奔来，反从胯下窜了。")],
          },
        ],
      },
      {
        scene_id: 4,
        title: "四角的天空",
        participants: ["我", "闰土"],
        beats: [
          {
            beat_id: 9,
            description: "跳鱼儿、五色的贝壳，我素不知道天下有这许多新鲜事。",
            is_key_event: false,
            evidence_refs: [ref(9, "我素不知道天下有这许多新鲜事：海边有如许五色的贝壳")],
          },
          {
            beat_id: 10,
            description: "往常的朋友，都和我一样只看见高墙上四角的天空。",
            is_key_event: true,
            evidence_refs: [ref(11, "他们都和我一样只看见院子里高墙上的四角的天空。")],
          },
        ],
      },
      {
        scene_id: 5,
        title: "正月离别",
        participants: ["我", "闰土", "忙月"],
        beats: [
          {
            beat_id: 11,
            description: "正月过去，闰土须回家里去，两个孩子都哭了。",
            is_key_event: true,
            evidence_refs: [ref(12, "可惜正月过去了，闰土须回家里去，我急得大哭，他也躲到厨房里，哭着不肯出门，但终于被他父亲带走了。")],
          },
          {
            beat_id: 12,
            description: "他托父亲捎来一包贝壳和几支鸟毛，从此没有再见面。",
            is_key_event: false,
            evidence_refs: [ref(12, "他后来还托他的父亲带给我一包贝壳和几支很好看的鸟毛")],
          },
        ],
      },
      {
        scene_id: 6,
        title: "二十年后",
        participants: ["我", "闰土", "母亲", "水生", "宏儿"],
        beats: [
          {
            beat_id: 13,
            description: "重逢时，闰土恭敬地叫了一声「老爷」。",
            is_key_event: true,
            evidence_refs: [ref(14, "他的态度终于恭敬起来了，分明的叫道：「老爷！……」")],
          },
          {
            beat_id: 14,
            description: "我们之间已经隔了一层可悲的厚障壁。",
            is_key_event: false,
            evidence_refs: [ref(15, "我似乎打了一个寒噤；我就知道，我们之间已经隔了一层可悲的厚障壁了。")],
          },
        ],
      },
    ],
  },

  start: "act1",
  finale: "converge",
  nodes: {
    // ── 第一幕 · 还原 ─────────────────────────────
    act1: [
      { t: "stage", stage: "stage2_reenacting" },
      {
        t: "narrate",
        scene: 1,
        text: "那一年，我家轮到一件大祭祀的值年。正月里供祖像，供品很多，祭器很讲究，拜的人也很多。",
      },
      { t: "narrate", text: "家里只有一个忙月，忙不过来。他便对父亲说，可以叫他的儿子闰土来管祭器。" },
      { t: "say", who: "忙月", text: "老爷放心，我那小子手脚勤，叫他来看着祭器，一样也少不了。" },
      { t: "narrate", text: "我早听到闰土这名字：和我仿佛年纪，闰月生的，五行缺土。他是能装弶捉小鸟雀的。" },
      { t: "narrate", text: "我于是日日盼望新年。新年到，闰土也就到了。" },
      { t: "say", who: "母亲", text: "迅儿，闰土来了，在厨房里呢。" },
      { t: "narrate", text: "我便飞跑的去看。他正在厨房里，紫色的圆脸，头戴一顶小毡帽，颈上套一个明晃晃的银项圈。" },
      {
        t: "quote",
        text: "紫色的圆脸，头戴一顶小毡帽，颈上套一个明晃晃的银项圈",
        note: "正月初见 · 选段第 4 段",
      },
      { t: "say", who: "母亲", text: "闰土，这是我家迅儿。你们年纪仿佛，一处玩去罢。" },
      { t: "narrate", text: "闰土见人很怕羞，躲在他父亲身后，只是偷偷地看我。" },
      {
        t: "choice",
        id: "greet",
        prompt: "闰土怯生生地看着你。你先开口说点什么？",
        hint: "选一项。有的选项是剧里其他角色的主意。",
        options: [
          {
            label: "「你就是闰土？听说你会捉鸟雀！」",
            say: "你就是闰土？听说你会装弶捉鸟雀，是真的么？",
            next: "greet-bird",
          },
          {
            label: "「你这银项圈真亮，是谁给你戴的？」",
            say: "你这银项圈真亮，是谁给你戴上的？",
            proposedBy: "母亲",
            next: "greet-ring",
          },
          {
            label: "拉他去看供桌上的祭器",
            act: "我拉起闰土的手，跑到供桌前，把那些讲究的祭器一样一样指给他看。",
            proposedBy: "忙月",
            next: "greet-altar",
          },
        ],
      },
    ],
    "greet-bird": [
      { t: "say", who: "闰土", text: "是真的。我爹教的，弶一装好，鸟雀自己就进来了。" },
      { t: "narrate", text: "说到捉鸟，他的眼睛亮了，也就不怕羞了。" },
      { t: "goto", to: "greet-end" },
    ],
    "greet-ring": [
      { t: "say", who: "闰土", text: "是爹在神佛面前许了愿，用圈子把我套住的，说这样就不会死去。" },
      { t: "narrate", text: "这可见他的父亲十分爱他。他摸着项圈，冲我笑了一笑。" },
      { t: "goto", to: "greet-end" },
    ],
    "greet-altar": [
      { t: "say", who: "闰土", text: "这么多祭器……爹说了，一样也不许少。我替你家看着！" },
      { t: "narrate", text: "他一本正经地站到供桌旁边，像个小卫兵。我笑了，他也笑了。" },
      { t: "goto", to: "greet-end" },
    ],
    "greet-end": [
      { t: "narrate", text: "没有旁人的时候，他便和我说话。于是不到半日，我们便熟识了。" },
      { t: "goto", to: "snow" },
    ],

    snow: [
      { t: "narrate", scene: 2, text: "第二日，我便要他捕鸟。" },
      { t: "say", who: "闰土", text: "这不能。须大雪下了才好。" },
      {
        t: "say",
        who: "闰土",
        text: "我们沙地上，下了雪，我扫出一块空地来，用短棒支起一个大竹匾，撒下秕谷。",
      },
      {
        t: "say",
        who: "闰土",
        text: "看鸟雀来吃时，我远远地将缚在棒上的绳子只一拉，那鸟雀就罩在竹匾下了。",
      },
      { t: "quote", text: "须大雪下了才好。", note: "雪地捕鸟 · 选段第 5 段" },
      {
        t: "choice",
        id: "snow",
        prompt: "闰土说得眉飞色舞。你想接着问什么？",
        options: [
          { label: "「都能捉到些什么鸟？」", say: "那都能捉到些什么鸟？", next: "snow-birds" },
          {
            label: "「可我们这里的雪，总是下不大……」",
            say: "可我们这里的雪，总是下不大……",
            next: "snow-sky",
          },
        ],
      },
    ],
    "snow-birds": [
      { t: "say", who: "闰土", text: "什么都有：稻鸡，角鸡，鹁鸪，蓝背……" },
      { t: "narrate", text: "这些鸟的名字，我一个也没听说过。" },
      { t: "goto", to: "snow-end" },
    ],
    "snow-sky": [
      { t: "say", who: "闰土", text: "那就等我们沙地上下。雪是白的，鸟是花的，好看着呢。" },
      { t: "goto", to: "snow-end" },
    ],
    "snow-end": [
      { t: "narrate", text: "我于是又很盼望下雪。" },
      { t: "goto", to: "moon" },
    ],

    moon: [
      { t: "narrate", scene: 3, text: "闰土又对我说起他家海边的夏天。" },
      {
        t: "say",
        who: "闰土",
        text: "现在太冷，你夏天到我们这里来。我们日里到海边捡贝壳去，红的绿的都有，鬼见怕也有，观音手也有。",
      },
      { t: "say", who: "闰土", text: "晚上我和爹管西瓜去，你也去。" },
      { t: "narrate", text: "我问他，是管贼么？" },
      {
        t: "say",
        who: "闰土",
        text: "不是。走路的人口渴了摘一个瓜吃，我们这里是不算偷的。要管的是獾猪，刺猬，猹。",
      },
      {
        t: "say",
        who: "闰土",
        text: "月亮底下，你听，啦啦的响了，猹在咬瓜了。你便捏了胡叉，轻轻地走去……",
      },
      {
        t: "narrate",
        text: "我的脑里忽然闪出一幅神异的图画来：深蓝的天空中挂着一轮金黄的圆月，下面是海边的沙地，都种着一望无际的碧绿的西瓜。",
      },
      { t: "quote", text: "深蓝的天空中挂着一轮金黄的圆月", note: "月下刺猹 · 选段第 1 段" },
      {
        t: "narrate",
        text: "其间有一个十一二岁的少年，项带银圈，手捏一柄钢叉，向一匹猹尽力的刺去。那猹却将身一扭，反从他的胯下逃走了。",
      },
      {
        t: "choice",
        id: "cha",
        prompt: "猹到底是什么？你心里有点怕，又有点想去。",
        options: [
          { label: "「他不咬人么？」", say: "他不咬人么？", next: "cha-bite" },
          {
            label: "「我也要去！到时候你教我刺猹。」",
            say: "我也要去！到时候你教我刺猹。",
            proposedBy: "闰土",
            next: "cha-learn",
          },
        ],
      },
    ],
    "cha-bite": [
      {
        t: "say",
        who: "闰土",
        text: "有胡叉呢。走到了，看见猹了，你便刺。这畜生很伶俐，倒向你奔来，反从胯下窜了。",
      },
      { t: "say", who: "闰土", text: "他的皮毛是油一般的滑……" },
      { t: "goto", to: "sky" },
    ],
    "cha-learn": [
      { t: "say", who: "闰土", text: "好！你来了，胡叉让给你使。不过那畜生滑得很，你可得捏紧了。" },
      { t: "narrate", text: "我们勾了勾手指。那时我还不知道，这个夏天，我终究没有去成。" },
      { t: "goto", to: "sky" },
    ],

    sky: [
      {
        t: "narrate",
        scene: 4,
        text: "我素不知道天下有这许多新鲜事：海边有如许五色的贝壳；西瓜有这样危险的经历，我先前单知道他在水果店里出卖罢了。",
      },
      { t: "say", who: "闰土", text: "我们沙地里，潮汛要来的时候，就有许多跳鱼儿只是跳，都有青蛙似的两个脚……" },
      { t: "narrate", text: "阿！闰土的心里有无穷无尽的希奇的事，都是我往常的朋友所不知道的。" },
      {
        t: "narrate",
        text: "他们不知道一些事，闰土在海边时，他们都和我一样只看见院子里高墙上的四角的天空。",
      },
      { t: "quote", text: "院子里高墙上的四角的天空", note: "四角的天空 · 选段第 12 段" },
      { t: "goto", to: "farewell" },
    ],

    farewell: [
      { t: "narrate", scene: 5, text: "可惜正月过去了，闰土须回家里去。" },
      { t: "say", who: "忙月", text: "闰土，收拾收拾，跟爹回去了。船在河埠头等着呢。" },
      { t: "say", who: "闰土", text: "爹……我再待一会儿，就一会儿。" },
      { t: "narrate", text: "乌篷船已经解了缆。闰土攥着衣角，一步一回头地看我。" },
      {
        t: "choice",
        id: "farewell",
        fate: true,
        prompt: "闰土就要上船了。这一别，就是二十年。你怎么送他？",
        hint: "这一选，会改变续写的开场和最后的结局。",
        options: [
          {
            label: "把最心爱的那本《花镜》塞进他手里",
            act: "我跑回书房，把最心爱的那本画着花鸟的《花镜》塞进闰土怀里。",
            say: "这个给你。上面画的鸟，你都认得。下回来，你教我认。",
            proposedBy: "母亲",
            set: { fate: "gift" },
            next: "fare-gift",
          },
          {
            label: "「夏天我一定去海边找你，说话算话！」",
            say: "夏天我一定去海边找你，你等着我，说话算话！",
            set: { fate: "promise" },
            next: "fare-promise",
          },
          {
            label: "哭着跑开，躲回屋里（课文里就是这样）",
            act: "我急得大哭，跑回屋里，再也不肯出来。",
            set: { fate: "origin" },
            next: "fare-origin",
          },
        ],
      },
    ],
    "fare-gift": [
      { t: "say", who: "闰土", text: "我……我没什么给你的。等我回去，给你捡一包顶好看的贝壳，还有鸟毛！" },
      { t: "narrate", text: "他把画册揣进怀里，用袖子擦了擦眼睛，跟着父亲上了船。" },
      { t: "goto", to: "act1-end" },
    ],
    "fare-promise": [
      { t: "say", who: "闰土", text: "说话算话！我给你留着最大的那个瓜，胡叉也给你磨亮了。" },
      { t: "narrate", text: "他站在船头冲我挥手，银项圈在晨光里一闪一闪，直到看不见。" },
      { t: "goto", to: "act1-end" },
    ],
    "fare-origin": [
      { t: "narrate", text: "他也躲到厨房里，哭着不肯出门，但终于被他父亲带走了。" },
      {
        t: "narrate",
        text: "他后来还托他的父亲带给我一包贝壳和几支很好看的鸟毛，我也曾送他一两次东西，但从此没有再见面。",
      },
      { t: "goto", to: "act1-end" },
    ],
    "act1-end": [
      { t: "wait", ms: 900 },
      { t: "stage", stage: "stage2_complete" },
      { t: "await", next: "act2" },
    ],

    // ── 第二幕 · 续写 ─────────────────────────────
    act2: [
      { t: "stage", stage: "stage3_extending" },
      {
        t: "narrate",
        scene: 6,
        text: "二十年后，我冒了严寒，回到相隔二千余里、别了二十余年的故乡去。苍黄的天底下，远近横着几个萧索的荒村。",
      },
      {
        t: "switch",
        key: "fate",
        cases: { gift: "act2-gift", promise: "act2-promise", origin: "act2-origin" },
        fallback: "act2-origin",
      },
    ],
    "act2-gift": [
      { t: "narrate", text: "书房的旧箱子里，还压着闰土托人捎来的那包贝壳。我送他的那本《花镜》，不知还在不在。" },
      { t: "goto", to: "reunion" },
    ],
    "act2-promise": [
      { t: "narrate", text: "那年说好夏天去海边找他，我一次也没有去成。这句话，在心里压了二十年。" },
      { t: "goto", to: "reunion" },
    ],
    "act2-origin": [
      { t: "narrate", text: "那年我哭着躲进屋里，连一句再见也没有说。从此，没有再见面。" },
      { t: "goto", to: "reunion" },
    ],
    reunion: [
      { t: "say", who: "母亲", text: "闰土常来问你，很想见你一回面。我已经将你到家的日期通知他，他也许就要来了。" },
      {
        t: "narrate",
        text: "来的便是闰土。他身材增加了一倍；先前紫色的圆脸，已经变作灰黄，而且加上了很深的皱纹。",
      },
      { t: "narrate", text: "他头上是一顶破毡帽，身上只一件极薄的棉衣。身后跟着一个孩子，颈上没有银圈。" },
      { t: "narrate", text: "我这时很兴奋，但不知道怎么说才好，只是说：阿！闰土哥，你来了？" },
      { t: "narrate", text: "他站住了，脸上现出欢喜和凄凉的神情；动着嘴唇，却没有作声。" },
      { t: "say", who: "闰土", text: "老爷！……" },
      { t: "narrate", text: "我似乎打了一个寒噤；我就知道，我们之间已经隔了一层可悲的厚障壁了。" },
      { t: "quote", text: "我们之间已经隔了一层可悲的厚障壁了", note: "《故乡》 · 课文之后" },
      { t: "narrate", text: "原文写到这里。接下来，由你改写。" },
      {
        t: "goals",
        goals: ["让闰土不再叫你「老爷」", "和闰土说起一件小时候的事", "让水生和宏儿成为朋友"],
      },
      { t: "goto", to: "hub" },
    ],
    hub: [
      { t: "when", all: ["goal1", "goal2", "goal3"], to: "converge" },
      {
        t: "choice",
        id: "hub",
        prompt: "闰土垂着手站在门口，等你开口。",
        hint: "可以选，也可以自己写一句。",
        options: [
          {
            label: "「别叫我老爷。还像小时候那样，叫我迅哥儿。」",
            say: "别叫我老爷。你还像小时候那样，叫我迅哥儿。",
            hideIf: "goal1",
            next: "g1",
          },
          {
            label: "「你还记得那年月下的西瓜地吗？」",
            say: "闰土哥，你还记得那年月下的西瓜地吗？",
            hideIf: "goal2",
            next: "g2",
          },
          {
            label: "「水生，过来。这是宏儿，你们一处玩去罢。」",
            say: "水生，过来。这是宏儿，和你差不多大，你们一处玩去罢。",
            proposedBy: "母亲",
            hideIf: "goal3",
            next: "g3",
          },
        ],
        free: {
          suggestions: [
            { text: "闰土哥，我们之间不用这么客气。", hideIf: "goal1" },
            { text: "你还记得那年雪地里捕鸟吗？", hideIf: "goal2" },
            { text: "让水生带宏儿去海边看跳鱼儿吧。", hideIf: "goal3" },
          ],
          // 按命中的关键词数取最贴近的一支，一样多时取靠前的。不收单字「哥」：
          // 「闰土哥，还记得……」是称呼，不是在说称呼的事
          routes: [
            { keywords: ["水生", "宏儿", "孩子", "儿子", "侄"], next: "g3", hideIf: "goal3" },
            { keywords: ["老爷", "迅哥", "客气", "称呼", "叫我", "兄弟"], next: "g1", hideIf: "goal1" },
            {
              keywords: ["猹", "瓜", "贝壳", "跳鱼", "鸟", "雪", "海边", "月", "小时候", "那年", "记得", "画册", "花镜", "约定", "胡叉", "项圈"],
              next: "g2",
              hideIf: "goal2",
            },
          ],
          fallback: "hub-miss",
        },
      },
    ],
    g1: [
      { t: "say", who: "闰土", text: "这成什么规矩。那时是孩子，不懂事……" },
      { t: "say", who: "母亲", text: "你们先前不是哥弟称呼么？还是照旧：迅哥儿。" },
      { t: "narrate", text: "闰土搓着手，半晌，终于低低地叫了一声。" },
      { t: "say", who: "闰土", text: "……迅哥儿。" },
      { t: "achieve", goal: 1 },
      { t: "goto", to: "hub" },
    ],
    g2: [
      {
        t: "switch",
        key: "fate",
        cases: { gift: "g2-gift", promise: "g2-promise", origin: "g2-origin" },
        fallback: "g2-origin",
      },
    ],
    "g2-gift": [
      { t: "say", who: "闰土", text: "记得。你送的那本画册，我一直收着。水生认鸟，就是照着上面认的。" },
      { t: "narrate", text: "他从怀里摸出一个油纸包，层层打开，正是那本《花镜》，边角磨得起了毛。" },
      { t: "achieve", goal: 2 },
      { t: "goto", to: "hub" },
    ],
    "g2-promise": [
      { t: "say", who: "闰土", text: "记得，怎么不记得。你说夏天要来，我给你留了一个顶大的瓜，一直留到烂在地里。" },
      { t: "narrate", text: "他说着笑起来，皱纹挤在一处。那笑里，有一点二十年前的样子。" },
      { t: "achieve", goal: 2 },
      { t: "goto", to: "hub" },
    ],
    "g2-origin": [
      { t: "say", who: "闰土", text: "记得……那年你躲在屋里哭，我在厨房里也哭。猹那东西滑得很，你还没见过呢。" },
      { t: "narrate", text: "他说着，竟有些不好意思，低下头去。" },
      { t: "achieve", goal: 2 },
      { t: "goto", to: "hub" },
    ],
    g3: [
      { t: "narrate", text: "水生躲在父亲背后，只露出半个头来。宏儿听得这话，便上去招他。" },
      { t: "say", who: "宏儿", text: "水生，你们那里的海边，真有跳鱼儿吗？带我去看！" },
      { t: "say", who: "水生", text: "有的。潮汛要来的时候，跳鱼儿只是跳……我带你去捡贝壳。" },
      { t: "narrate", text: "两个孩子一前一后跑出去了。闰土看着他们的背影，嘴角动了一动。" },
      { t: "achieve", goal: 3 },
      { t: "goto", to: "hub" },
    ],
    "hub-miss": [
      { t: "say", who: "闰土", text: "非常难。第六个孩子也会帮忙了，却总是吃不够……又不太平。" },
      { t: "narrate", text: "他只是摇头，像一个石像。这一句，没有碰到他心里那块地方。" },
      { t: "goto", to: "hub" },
    ],

    // ── 收束与结局 ───────────────────────────────
    converge: [
      { t: "narrate", text: "那天，闰土在我家坐到很晚。" },
      {
        t: "switch",
        key: "fate",
        cases: { gift: "end-gift", promise: "end-promise", origin: "end-origin" },
        fallback: "end-origin",
      },
    ],
    "end-gift": [
      { t: "narrate", text: "临走，他从船舱里拎上来一包贝壳：红的绿的都有，鬼见怕也有，观音手也有。" },
      { t: "narrate", text: "二十年前的那一包，二十年后的这一包，一样的好看。" },
      { t: "end", ending: "shells" },
    ],
    "end-promise": [
      { t: "narrate", text: "第二天一早，我跟着闰土的船，去了他家的海边。" },
      {
        t: "narrate",
        text: "沙地上的西瓜早已罢园，跳鱼儿还在潮水边上跳。我们沿着海滩走，脚印一行一行，被潮水抹去，又踩出来。",
      },
      { t: "quote", text: "其实地上本没有路，走的人多了，也便成了路。", note: "《故乡》 · 结尾" },
      { t: "end", ending: "road" },
    ],
    "end-origin": [
      { t: "narrate", text: "临走，他还是叫了一声迅哥儿，声音很轻。船开出去，两岸的青山在黄昏中，都装成了深黛颜色。" },
      {
        t: "narrate",
        text: "宏儿和水生约好了，明年还要一同去看跳鱼儿。我希望他们不再像我们，又大家隔膜起来。",
      },
      { t: "end", ending: "sky" },
    ],
  },

  endings: [
    {
      id: "shells",
      title: "一包贝壳",
      art: "/demo/runtu/end-shells.svg",
      lines: [
        "二十年前，闰土托父亲捎来一包贝壳；二十年后，他又拎来一包。",
        "你送出的那本画册，被一个不识字的父亲收了二十年，教会了他的孩子认鸟。",
      ],
      teaser: "临别时，送他一样东西。",
    },
    {
      id: "road",
      title: "海边的路",
      art: "/demo/runtu/end-road.svg",
      lines: [
        "你没有让那句「夏天我一定去」落空。",
        "希望本是无所谓有，无所谓无的。这正如地上的路；其实地上本没有路，走的人多了，也便成了路。",
      ],
      teaser: "临别时，许他一个约定。",
    },
    {
      id: "sky",
      title: "四角的天空",
      art: "/demo/runtu/end-sky.svg",
      lines: [
        "课文里，两个孩子哭着分别，从此再没见面。",
        "你没能改写那一场分别，却让下一代不再隔膜：水生和宏儿，约好了一同去看跳鱼儿。",
      ],
      teaser: "照着课文，哭着分别。",
    },
  ],

  seals: [
    { id: "restore", glyph: "还原", name: "还原", desc: "完整演完了课文里的少年时光" },
    { id: "bond", glyph: "知音", name: "知音", desc: "续写目标全部达成" },
    { id: "rewrite", glyph: "改写", name: "改写", desc: "在命运抉择里走出了课文之外的一条路" },
    { id: "parallel", glyph: "平行", name: "平行世界", desc: "回到抉择点，看了另一条路" },
    { id: "collect", glyph: "拾遗", name: "拾遗", desc: "拾齐了书匣里的全部原句" },
  ],
};
