/**
 * 演出台本《鸿门宴》（司马迁《史记·项羽本纪》节选，作品已进入公有领域）。
 *
 * 你演项羽。还原五场：军帐夜怒 → 项伯夜归 → 鸿门谢罪 → 举玦舞剑 → 樊哙闯帐。
 * 第四场范增第三次举玦是命运抉择：默然不应（课文）、点头、向沛公举杯，三条路各有一段
 * 不同的席间变故，最后都落到沛公脱身、亚父破玉斗。续写一场：宴罢当夜，亚父要走，
 * 叔父不语，樊哙那一问你还没答；三个续写目标全部达成后收束到结局。
 *
 * 台词以原文为准，原文没有的部分照人物的说话方式补写（浅近文言）；项羽在原文里的话
 * 写进旁白或做成选项，你演的角色只说你自己选的、写的话——和真实游戏一样。
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

const ROLE = "项羽";

export const HONGMEN: DemoScript = {
  slug: "hongmen",
  shelf: {
    grade: "高中 · 必修下",
    source: "司马迁《史记·项羽本纪》节选",
    minutes: 8,
    blurb:
      "范增三次举玦，项庄拔剑起舞，樊哙闯帐瞋目。你来演项羽：那一席酒宴上，默然不应，还是点头？宴罢之后，再答一回樊哙那一问。",
    cover: "/demo/hongmen/bg-banquet.svg",
  },
  playerRole: ROLE,
  backgrounds: {
    1: "/demo/hongmen/bg-tent.svg",
    2: "/demo/hongmen/bg-camp.svg",
    3: "/demo/hongmen/bg-gate.svg",
    4: "/demo/hongmen/bg-banquet.svg",
    5: "/demo/hongmen/bg-fankuai.svg",
    6: "/demo/hongmen/bg-aftermath.svg",
  },
  castNotes: {
    项羽: "你来演。四十万楚军的统帅，这一席酒宴的主人。",
    范增: "AI 来演。项羽的谋士，尊称亚父。",
    项伯: "AI 来演。项羽的叔父，张良的旧交。",
    刘邦: "AI 来演。沛公，带百余骑来鸿门谢罪。",
    张良: "AI 来演。沛公的谋士。",
    樊哙: "AI 来演。沛公的参乘，第五场登场。",
    项庄: "AI 来演。项羽的堂弟，奉命舞剑。",
  },
  quoteTotal: 7,
  package: {
    schema_version: V,
    title: "鸿门宴",
    teaching_focus: [
      "从语言、动作、神态描写中分析项羽、刘邦、樊哙、范增的形象",
      "梳理鸿门宴上矛盾冲突的起伏",
      "积累「项庄舞剑，意在沛公」「人为刀俎，我为鱼肉」等成语",
    ],
    playable_roles: ["项羽", "刘邦"],
    stage2_ending_beat_id: 15,
    characters: [
      {
        name: "项羽",
        public_background:
          "名籍，字羽，楚国名将项燕之后。巨鹿一战破秦军主力，诸侯将莫敢仰视。此时拥兵四十万，驻在新丰鸿门，人称项王。",
        personality_traits: [
          { label: "勇武", evidence: "项王按剑而跽", behavior: "遇事先按剑" },
          { label: "直率", evidence: "此沛公左司马曹无伤言之", behavior: "心里有什么就说什么" },
          { label: "不忍", evidence: "君王为人不忍", behavior: "到了下手的时候犹豫" },
        ],
        speech_style: null,
        knowledge_boundary: { knows: ["军中兵力", "曹无伤的密报"], not_knows: ["项伯夜访张良的内情", "沛公的退路"] },
        is_player_playable: { value: true, reason: "课文的核心人物，几次抉择都落在他身上" },
      },
      {
        name: "范增",
        public_background: "项羽的谋士，年过七十，项羽尊称他为亚父。看出沛公「其志不在小」，力主在鸿门除掉他。",
        personality_traits: [
          { label: "深谋", evidence: "此其志不在小", behavior: "看人看到十年以后" },
          { label: "急躁", evidence: "拔剑撞而破之", behavior: "怒气藏不住" },
        ],
        speech_style: null,
        knowledge_boundary: { knows: ["沛公的志向", "天子气之说"], not_knows: ["项伯夜访张良"] },
        is_player_playable: { value: false, reason: "戏份集中在举玦与破斗" },
      },
      {
        name: "项伯",
        public_background:
          "项羽的叔父，楚左尹。素与张良交好，受过张良的活命之恩。鸿门宴前夜私下驰入沛公军，又回来替沛公说情。",
        personality_traits: [
          { label: "重私恩", evidence: "素善留侯张良", behavior: "念旧情胜过军令" },
          { label: "护人", evidence: "常以身翼蔽沛公", behavior: "关键时刻挡在前面" },
        ],
        speech_style: null,
        knowledge_boundary: { knows: ["与沛公约为婚姻"], not_knows: ["范增的安排"] },
        is_player_playable: { value: false, reason: "戏份较少" },
      },
      {
        name: "刘邦",
        public_background: "沛公。先破秦入咸阳，还军霸上，兵十万。听说项羽要来攻，第二天一早只带百余骑来鸿门谢罪。",
        personality_traits: [
          { label: "能屈能伸", evidence: "臣与将军戮力而攻秦", behavior: "低头说软话" },
          { label: "果断", evidence: "沛公至军，立诛杀曹无伤", behavior: "脱身之后立刻清算" },
        ],
        speech_style: null,
        knowledge_boundary: { knows: ["项伯的来意", "郦山小路"], not_knows: ["范增的安排"] },
        is_player_playable: { value: true, reason: "另一个视角：在刀俎之下脱身" },
      },
      {
        name: "张良",
        public_background: "沛公的谋士，韩国贵族之后，救过项伯的命。席间西向侍坐，危急时出帐召来樊哙，最后留下替沛公谢罪。",
        personality_traits: [{ label: "沉着", evidence: "沛公不胜桮杓，不能辞", behavior: "替人收场，礼数周全" }],
        speech_style: null,
        knowledge_boundary: { knows: ["项伯夜访", "沛公的退路"], not_knows: ["范增的安排"] },
        is_player_playable: { value: false, reason: "戏份较少" },
      },
      {
        name: "樊哙",
        public_background: "沛公的参乘（贴身卫士），屠狗出身。听说项庄舞剑，带剑拥盾闯进军帐。",
        personality_traits: [
          { label: "勇猛", evidence: "头发上指，目眦尽裂", behavior: "先闯进去再说" },
          { label: "粗中有细", evidence: "劳苦而功高如此，未有封侯之赏", behavior: "话说得比谁都在理" },
        ],
        speech_style: null,
        knowledge_boundary: { knows: ["沛公入关后的作为"], not_knows: ["范增的安排"] },
        is_player_playable: { value: false, reason: "第五场登场" },
      },
      {
        name: "项庄",
        public_background: "项羽的堂弟。奉范增之命入帐为寿，借舞剑之名刺杀沛公。",
        personality_traits: [{ label: "听命", evidence: "请以剑舞", behavior: "照亚父的安排行事" }],
        speech_style: null,
        knowledge_boundary: { knows: ["范增的安排"], not_knows: ["项伯的心思"] },
        is_player_playable: { value: false, reason: "戏份较少" },
      },
    ],
    scenes: [
      {
        scene_id: 1,
        title: "军帐夜怒",
        participants: ["项羽", "范增"],
        beats: [
          {
            beat_id: 1,
            description: "曹无伤派人密报：沛公想在关中称王。",
            is_key_event: true,
            evidence_refs: [ref(0, "沛公左司马曹无伤使人言于项羽曰：「沛公欲王关中，使子婴为相，珍宝尽有之。」")],
          },
          {
            beat_id: 2,
            description: "项羽大怒，下令明日犒军，击破沛公。",
            is_key_event: false,
            evidence_refs: [ref(0, "项羽大怒，曰：「旦日飨士卒，为击破沛公军！」")],
          },
          {
            beat_id: 3,
            description: "范增劝项羽急击：此其志不在小。",
            is_key_event: true,
            evidence_refs: [ref(0, "今入关，财物无所取，妇女无所幸，此其志不在小。")],
          },
        ],
      },
      {
        scene_id: 2,
        title: "项伯夜归",
        participants: ["项羽", "项伯"],
        beats: [
          {
            beat_id: 4,
            description: "项伯连夜驰入沛公军，私见张良。",
            is_key_event: false,
            evidence_refs: [ref(1, "项伯乃夜驰之沛公军，私见张良，具告以事")],
          },
          {
            beat_id: 5,
            description: "项伯回营替沛公说情，项王许诺。",
            is_key_event: true,
            evidence_refs: [ref(3, "今人有大功而击之，不义也，不如因善遇之。」项王许诺。")],
          },
        ],
      },
      {
        scene_id: 3,
        title: "鸿门谢罪",
        participants: ["项羽", "刘邦", "项伯", "范增", "张良"],
        beats: [
          {
            beat_id: 6,
            description: "沛公带百余骑来鸿门谢罪。",
            is_key_event: true,
            evidence_refs: [ref(4, "沛公旦日从百余骑来见项王，至鸿门，谢曰")],
          },
          {
            beat_id: 7,
            description: "项王说出了告密的曹无伤。",
            is_key_event: true,
            evidence_refs: [ref(4, "此沛公左司马曹无伤言之；不然，籍何以至此？")],
          },
          {
            beat_id: 8,
            description: "项王留沛公饮酒，分坐东西南北。",
            is_key_event: false,
            evidence_refs: [ref(4, "项王、项伯东向坐，亚父南向坐。亚父者，范增也。沛公北向坐，张良西向侍。")],
          },
        ],
      },
      {
        scene_id: 4,
        title: "举玦舞剑",
        participants: ["项羽", "范增", "项庄", "项伯", "刘邦"],
        beats: [
          {
            beat_id: 9,
            description: "范增三次举玦，项王默然不应。",
            is_key_event: true,
            evidence_refs: [ref(4, "范增数目项王，举所佩玉玦以示之者三，项王默然不应。")],
          },
          {
            beat_id: 10,
            description: "项庄入帐为寿，请以剑舞。",
            is_key_event: false,
            evidence_refs: [ref(4, "君王与沛公饮，军中无以为乐，请以剑舞。")],
          },
          {
            beat_id: 11,
            description: "项伯拔剑起舞，以身翼蔽沛公。",
            is_key_event: true,
            evidence_refs: [ref(4, "项伯亦拔剑起舞，常以身翼蔽沛公，庄不得击。")],
          },
        ],
      },
      {
        scene_id: 5,
        title: "樊哙闯帐",
        participants: ["项羽", "樊哙", "张良", "刘邦", "范增"],
        beats: [
          {
            beat_id: 12,
            description: "樊哙带剑拥盾闯入，瞋目视项王。",
            is_key_event: true,
            evidence_refs: [ref(5, "披帷西向立，瞋目视项王，头发上指，目眦尽裂。")],
          },
          {
            beat_id: 13,
            description: "樊哙陈辞，项王未有以应。",
            is_key_event: true,
            evidence_refs: [ref(5, "劳苦而功高如此，未有封侯之赏，而听细说，欲诛有功之人。此亡秦之续耳")],
          },
          {
            beat_id: 14,
            description: "沛公借如厕脱身，留张良谢罪。",
            is_key_event: false,
            evidence_refs: [ref(6, "如今人方为刀俎，我为鱼肉，何辞为？")],
          },
          {
            beat_id: 15,
            description: "亚父撞破玉斗：竖子不足与谋。",
            is_key_event: true,
            evidence_refs: [ref(7, "亚父受玉斗，置之地，拔剑撞而破之")],
          },
        ],
      },
      {
        scene_id: 6,
        title: "宴罢当夜",
        participants: ["项羽", "范增", "项伯"],
        beats: [
          {
            beat_id: 16,
            description: "沛公回到霸上，立诛曹无伤。",
            is_key_event: false,
            evidence_refs: [ref(8, "沛公至军，立诛杀曹无伤。")],
          },
          {
            beat_id: 17,
            description: "樊哙那一问，项王还没有回答。",
            is_key_event: true,
            evidence_refs: [ref(5, "项王未有以应，曰：「坐。」")],
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
        text: "秦已经亡了。你领着四十万大军驻在新丰鸿门；沛公的十万人马驻在霸上。两军相去四十里。",
      },
      { t: "narrate", text: "这天夜里，沛公的左司马曹无伤派人来见你，只带了一句话：" },
      { t: "narrate", text: "「沛公欲王关中，使子婴为相，珍宝尽有之。」" },
      { t: "narrate", text: "关中的王位，降了的秦王子婴，咸阳的珍宝——沛公全都要。" },
      {
        t: "choice",
        id: "rage",
        prompt: "帐中诸将都看着你。你一拍案——",
        hint: "选一项。有的选项是剧里其他角色的主意。",
        options: [
          {
            label: "「旦日飨士卒，为击破沛公军！」",
            say: "旦日飨士卒，为击破沛公军！",
            next: "rage-war",
          },
          {
            label: "「先不声张。请亚父来议。」",
            say: "先不声张。请亚父来议。",
            next: "rage-council",
          },
          {
            label: "「叫来人再说一遍——沛公真敢如此？」",
            say: "叫来人再说一遍。沛公，真敢如此？",
            next: "rage-ask",
          },
        ],
      },
    ],
    "rage-war": [
      { t: "narrate", text: "帐中诸将齐声应诺：明日一早犒赏士卒，然后踏平霸上。" },
      { t: "goto", to: "rage-end" },
    ],
    "rage-council": [
      { t: "narrate", text: "不多时，亚父范增披衣而来。他听完，捻着胡须，沉默了片刻。" },
      { t: "goto", to: "rage-end" },
    ],
    "rage-ask": [
      { t: "narrate", text: "来人伏在地上，又说了一遍，一字不差。你的手按在了剑柄上。" },
      { t: "goto", to: "rage-end" },
    ],
    "rage-end": [
      {
        t: "say",
        who: "范增",
        text: "沛公居山东时，贪于财货，好美姬。今入关，财物无所取，妇女无所幸，此其志不在小。",
      },
      { t: "quote", text: "此其志不在小", note: "军帐夜怒 · 选段第 1 段" },
      { t: "say", who: "范增", text: "吾令人望其气，皆为龙虎，成五采，此天子气也。急击勿失！" },
      { t: "narrate", text: "亚父说得明白：一个贪财好色的人，进了咸阳却什么也不拿，他图的是整个天下。" },
      { t: "goto", to: "uncle" },
    ],

    uncle: [
      { t: "narrate", scene: 2, text: "同一夜，楚营里有一个人悄悄出了营门。" },
      { t: "narrate", text: "他是你的叔父，楚左尹项伯。他和沛公的谋士张良是旧交，张良救过他的命。" },
      { t: "narrate", text: "项伯连夜驰入沛公军中，私下见了张良……这些，你还不知道。" },
      { t: "narrate", text: "后半夜，项伯回来了，径直走进你的大帐。" },
      { t: "say", who: "项伯", text: "沛公不先破关中，公岂敢入乎？今人有大功而击之，不义也。" },
      { t: "say", who: "项伯", text: "不如因善遇之。" },
      {
        t: "narrate",
        text: "他说：沛公若不先打下关中，你哪里进得来？人家有大功，你却要打他，这是不义。不如好好待他。",
      },
      {
        t: "choice",
        id: "uncle",
        prompt: "叔父深夜来替沛公说情。你怎么答他？",
        options: [
          { label: "「诺。」", say: "诺。", next: "uncle-yes" },
          {
            label: "「叔父深夜往沛公营中，所为何事？」",
            say: "叔父深夜往沛公营中，所为何事？",
            set: { doubt: "yes" },
            next: "uncle-doubt",
          },
          {
            label: "「他明日若不来谢罪，再击不迟。」",
            say: "他明日若不来鸿门谢罪，再击不迟。",
            proposedBy: "项伯",
            next: "uncle-wait",
          },
        ],
      },
    ],
    "uncle-yes": [
      { t: "narrate", text: "你许诺了。叔父松了一口气，退出帐去。" },
      { t: "goto", to: "uncle-end" },
    ],
    "uncle-doubt": [
      { t: "say", who: "项伯", text: "……沛公派人来请，我便去了一趟。他确无反意。" },
      { t: "narrate", text: "叔父说得很快，眼睛没有看你。你没有再问。" },
      { t: "goto", to: "uncle-end" },
    ],
    "uncle-wait": [
      { t: "say", who: "项伯", text: "他必来。我已同他说好了。" },
      { t: "narrate", text: "「说好了」三个字，你当时没有在意。" },
      { t: "goto", to: "uncle-end" },
    ],
    "uncle-end": [
      { t: "narrate", text: "第二天的犒军，就这样搁下了。" },
      { t: "goto", to: "xie" },
    ],

    xie: [
      { t: "narrate", scene: 3, text: "第二天一早，沛公只带了百余骑来到鸿门，一见你，便下拜谢罪。" },
      {
        t: "say",
        who: "刘邦",
        text: "臣与将军戮力而攻秦，将军战河北，臣战河南，然不自意能先入关破秦，得复见将军于此。",
      },
      { t: "say", who: "刘邦", text: "今者有小人之言，令将军与臣有郤。" },
      { t: "narrate", text: "他把自己说成你的同伴，把先入关中说成侥幸，又把这场风波推给了「小人」。" },
      {
        t: "choice",
        id: "xie",
        prompt: "沛公拜在阶下，满座都在看你。你怎么回他？",
        options: [
          {
            label: "「此沛公左司马曹无伤言之；不然，籍何以至此？」",
            say: "此沛公左司马曹无伤言之；不然，籍何以至此？",
            set: { wushang: "told" },
            next: "xie-told",
          },
          {
            label: "「沛公不必多言。入座，饮酒。」",
            say: "沛公不必多言。入座，饮酒。",
            proposedBy: "项伯",
            next: "xie-drink",
          },
          {
            label: "「小人之言？那守函谷关的兵，也是小人派的？」",
            say: "小人之言？那守函谷关、拦着籍的兵，也是小人派的？",
            proposedBy: "范增",
            next: "xie-press",
          },
        ],
      },
    ],
    "xie-told": [
      { t: "narrate", text: "你一句话，把报信的人供了出来。沛公神色不动，只是又拜了一拜。" },
      { t: "goto", to: "xie-end" },
    ],
    "xie-drink": [
      { t: "narrate", text: "沛公连声称谢。亚父在一旁，眉头皱了起来。" },
      { t: "goto", to: "xie-end" },
    ],
    "xie-press": [
      { t: "say", who: "刘邦", text: "所以遣将守关者，备他盗之出入与非常也。日夜望将军至，岂敢反乎！" },
      { t: "narrate", text: "他答得滴水不漏，像是早就备好了这句话。" },
      { t: "goto", to: "xie-end" },
    ],
    "xie-end": [
      { t: "narrate", text: "当天，你留沛公在帐中饮酒。" },
      { t: "narrate", text: "你和项伯东向坐，亚父南向坐，沛公北向坐，张良西向侍。东向为尊，沛公坐在下首。" },
      { t: "goto", to: "jue" },
    ],

    jue: [
      { t: "narrate", scene: 4, text: "酒过数巡。亚父范增几次拿眼色看你。" },
      { t: "narrate", text: "他举起腰间佩的玉玦，向你示意。你看见了，没有动。" },
      { t: "narrate", text: "第二次，玉玦举得更高。沛公低头饮酒，像什么也没看见。" },
      { t: "quote", text: "举所佩玉玦以示之者三", note: "举玦舞剑 · 选段第 5 段" },
      { t: "narrate", text: "第三次。满座只有你和亚父知道：玦者，决也。他在催你下决断。" },
      {
        t: "choice",
        id: "jue",
        fate: true,
        prompt: "亚父第三次举起了玉玦。沛公就坐在你对面。你——",
        hint: "这一选，会改变这一席酒宴的走向和最后的结局。",
        options: [
          {
            label: "默然不应（课文里就是这样）",
            act: "你端着酒杯，默然不应。",
            set: { fate: "origin" },
            next: "jue-origin",
          },
          {
            label: "迎着亚父的目光，微微点头",
            act: "你迎着亚父的目光，微微点了一下头。",
            proposedBy: "范增",
            set: { fate: "nod" },
            next: "jue-nod",
          },
          {
            label: "「沛公，满饮此杯。前事一笔勾销。」",
            say: "沛公，满饮此杯。前事，一笔勾销。",
            proposedBy: "项伯",
            set: { fate: "pardon" },
            next: "jue-pardon",
          },
        ],
      },
    ],
    "jue-origin": [
      { t: "narrate", text: "亚父的手慢慢放下。他起身出帐，召来了你的堂弟项庄。" },
      { t: "say", who: "范增", text: "君王为人不忍。若入前为寿，寿毕，请以剑舞，因击沛公于坐，杀之。" },
      { t: "say", who: "范增", text: "不者，若属皆且为所虏。" },
      { t: "say", who: "项庄", text: "君王与沛公饮，军中无以为乐，请以剑舞。" },
      { t: "narrate", text: "你说：诺。" },
      {
        t: "narrate",
        text: "项庄拔剑起舞，剑锋几次掠过沛公案前。项伯也拔剑起舞，常以身翼蔽沛公，项庄不得击。",
      },
      { t: "goto", to: "fan" },
    ],
    "jue-nod": [
      { t: "narrate", text: "亚父眼中一亮，起身出帐。不多时，项庄捧剑入帐。" },
      { t: "say", who: "项庄", text: "君王与沛公饮，军中无以为乐，请以剑舞。" },
      { t: "narrate", text: "剑光一闪，直取沛公案前。项伯拍案而起，拔剑相迎，以身翼蔽沛公。" },
      { t: "say", who: "项伯", text: "籍儿！鸿门设宴，诸侯都看着。你要在席上杀客么？" },
      { t: "narrate", text: "两柄剑在沛公身前交错。沛公脸色煞白，酒洒了一身。" },
      { t: "goto", to: "fan" },
    ],
    "jue-pardon": [
      { t: "say", who: "刘邦", text: "谢将军！" },
      { t: "narrate", text: "沛公一饮而尽。亚父的脸色铁青，拂袖出帐。不多时，项庄入帐为寿。" },
      { t: "say", who: "项庄", text: "君王与沛公饮，军中无以为乐，请以剑舞。" },
      { t: "narrate", text: "剑锋几次掠过沛公案前。你看出来了——这是亚父的意思。项伯也拔剑起舞，以身翼蔽沛公。" },
      {
        t: "narrate",
        text: "你把酒杯往案上一顿：「项庄，退下。籍说过了，前事一笔勾销。」项庄收了剑。帐外，却已经乱了起来。",
      },
      { t: "goto", to: "fan" },
    ],

    fan: [
      { t: "narrate", scene: 5, text: "帐外，张良匆匆走到军门，找到了沛公的参乘樊哙。" },
      { t: "say", who: "樊哙", text: "今日之事何如？" },
      { t: "say", who: "张良", text: "甚急！今者项庄拔剑舞，其意常在沛公也。" },
      { t: "quote", text: "今者项庄拔剑舞，其意常在沛公也", note: "樊哙闯帐 · 选段第 6 段" },
      { t: "say", who: "樊哙", text: "此迫矣！臣请入，与之同命。" },
      { t: "narrate", text: "樊哙带剑拥盾闯入军门。交戟的卫士要拦，他侧过盾牌一撞，卫士仆地。" },
      { t: "narrate", text: "他掀开帷帐，西向而立，瞋目直视着你：头发上指，目眦尽裂。" },
      { t: "quote", text: "头发上指，目眦尽裂", note: "樊哙闯帐 · 选段第 6 段" },
      {
        t: "choice",
        id: "fan",
        prompt: "一个满脸怒气的壮士闯进帐来，直瞪着你。你——",
        options: [
          { label: "按剑而跽：「客何为者？」", act: "你按剑而跽，直起了身子。", say: "客何为者？", next: "fan-who" },
          { label: "「壮士！赐之卮酒。」", say: "壮士！赐之卮酒。", next: "fan-wine" },
          {
            label: "「赐之彘肩——看他敢不敢吃。」",
            say: "赐之彘肩！",
            proposedBy: "项庄",
            next: "fan-pork",
          },
        ],
      },
    ],
    "fan-who": [
      { t: "say", who: "张良", text: "沛公之参乘樊哙者也。" },
      { t: "narrate", text: "你看着这个人，忽然笑了：壮士！赐之卮酒。" },
      { t: "goto", to: "fan-eat" },
    ],
    "fan-wine": [
      { t: "narrate", text: "左右捧上满满一大斗酒。" },
      { t: "goto", to: "fan-eat" },
    ],
    "fan-pork": [
      { t: "narrate", text: "左右拿来一只生猪腿。帐中有人低声笑了起来。" },
      { t: "goto", to: "fan-eat" },
    ],
    "fan-eat": [
      {
        t: "narrate",
        text: "樊哙拜谢，起身，立而饮之。又把盾牌覆在地上，放上生彘肩，拔剑切而啖之。",
      },
      { t: "narrate", text: "你问他：壮士，能复饮乎？" },
      { t: "say", who: "樊哙", text: "臣死且不避，卮酒安足辞！" },
      {
        t: "say",
        who: "樊哙",
        text: "沛公先破秦入咸阳，毫毛不敢有所近，封闭宫室，还军霸上，以待大王来。",
      },
      {
        t: "say",
        who: "樊哙",
        text: "劳苦而功高如此，未有封侯之赏，而听细说，欲诛有功之人。此亡秦之续耳，窃为大王不取也！",
      },
      { t: "narrate", text: "满座寂然。你张了张口，竟答不上来，只说了一个字：坐。" },
      {
        t: "switch",
        key: "fate",
        cases: { origin: "esc-origin", nod: "esc-nod", pardon: "esc-pardon" },
        fallback: "esc-origin",
      },
    ],
    "esc-origin": [
      { t: "narrate", text: "坐了一会儿，沛公起身如厕，把樊哙也招了出去。" },
      { t: "say", who: "樊哙", text: "大行不顾细谨，大礼不辞小让。如今人方为刀俎，我为鱼肉，何辞为？" },
      { t: "quote", text: "如今人方为刀俎，我为鱼肉", note: "樊哙闯帐 · 选段第 7 段" },
      { t: "narrate", text: "沛公扔下车骑，独自一骑，从郦山下抄小路回了霸上，只留张良入帐谢罪。" },
      {
        t: "say",
        who: "张良",
        text: "沛公不胜桮杓，不能辞。谨使臣良奉白璧一双，再拜献大王足下；玉斗一双，再拜奉大将军足下。",
      },
      { t: "narrate", text: "你问：沛公安在？张良答：闻大王有意督过之，脱身独去，已至军矣。" },
      { t: "narrate", text: "你受了白璧，置之坐上。亚父受了玉斗，置之地，拔剑撞而破之。" },
      { t: "goto", to: "smash" },
    ],
    "esc-nod": [
      { t: "narrate", text: "坐了一会儿，沛公起身如厕，把樊哙也招了出去。你那一下点头，他们都看见了。" },
      { t: "say", who: "樊哙", text: "大行不顾细谨，大礼不辞小让。如今人方为刀俎，我为鱼肉，何辞为？" },
      { t: "quote", text: "如今人方为刀俎，我为鱼肉", note: "樊哙闯帐 · 选段第 7 段" },
      { t: "narrate", text: "等你发觉，沛公已经从郦山小路逃回霸上。张良捧着白璧入帐，礼数周全，一句不提那柄剑。" },
      { t: "narrate", text: "亚父盯着你，把玉斗往地上一放，拔剑撞得粉碎。" },
      { t: "goto", to: "smash" },
    ],
    "esc-pardon": [
      { t: "narrate", text: "坐了一会儿，沛公起身告辞。你没有留他，只说：改日再饮。" },
      { t: "narrate", text: "走到军门，沛公还想回头再谢一回。樊哙一把拉住了他。" },
      { t: "say", who: "樊哙", text: "大行不顾细谨，大礼不辞小让。如今人方为刀俎，我为鱼肉，何辞为？" },
      { t: "quote", text: "如今人方为刀俎，我为鱼肉", note: "樊哙闯帐 · 选段第 7 段" },
      { t: "narrate", text: "张良留下来，献上白璧一双、玉斗一双。亚父受了玉斗，置之地，拔剑撞而破之。" },
      { t: "goto", to: "smash" },
    ],
    smash: [
      { t: "say", who: "范增", text: "唉！竖子不足与谋。夺项王天下者，必沛公也，吾属今为之虏矣！" },
      { t: "quote", text: "唉！竖子不足与谋", note: "樊哙闯帐 · 选段第 8 段" },
      { t: "switch", key: "wushang", cases: { told: "wushang-dead" }, fallback: "wushang-alive" },
    ],
    "wushang-dead": [
      { t: "narrate", text: "当天，沛公回到霸上，立诛杀曹无伤。" },
      { t: "quote", text: "沛公至军，立诛杀曹无伤。", note: "结尾 · 选段第 9 段" },
      { t: "narrate", text: "是你在席上说出了他的名字。" },
      { t: "goto", to: "act1-end" },
    ],
    "wushang-alive": [
      { t: "narrate", text: "当天，沛公回到霸上，查了一夜，没有查出是谁报的信。曹无伤的名字，你没有说出口。" },
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
      { t: "narrate", scene: 6, text: "当夜，鸿门楚营。宾客早已散尽。" },
      { t: "say", who: "项庄", text: "禀君王：沛公已回霸上，营中灯火未熄。" },
      { t: "narrate", text: "项庄退了出去。帐中只剩下你、亚父和叔父项伯。" },
      {
        t: "switch",
        key: "fate",
        cases: { origin: "act2-origin", nod: "act2-nod", pardon: "act2-pardon" },
        fallback: "act2-origin",
      },
    ],
    "act2-origin": [
      { t: "narrate", text: "白璧还放在你的坐上。地上是碎了的玉斗，亚父没有让人去扫。" },
      { t: "goto", to: "night" },
    ],
    "act2-nod": [
      { t: "narrate", text: "你点过的那一下头，满座都看见了。沛公知道你想杀他，你却还是让他走了。" },
      { t: "goto", to: "night" },
    ],
    "act2-pardon": [
      { t: "narrate", text: "你在满座宾客面前说了「一笔勾销」。从那时起，亚父就没有再看你一眼。" },
      { t: "goto", to: "night" },
    ],
    night: [
      { t: "narrate", text: "亚父站起身，向你一揖到地。" },
      { t: "say", who: "范增", text: "天下事大定矣，君王自为之。愿赐骸骨归卒伍。" },
      { t: "narrate", text: "他是要辞官回乡。史书里，他后来真的走了，还没走到彭城，就病死在路上。" },
      { t: "say", who: "项伯", text: "亚父言重了。今日之事，原是……" },
      { t: "narrate", text: "叔父说了半句，又咽了回去，退到灯影里。樊哙那一问，你也还没有答。" },
      { t: "narrate", text: "课文写到这里。接下来，由你改写。" },
      { t: "goals", goals: ["留住要走的亚父", "问出是谁走漏了出兵的消息", "回答樊哙那一问"] },
      { t: "goto", to: "hub" },
    ],
    hub: [
      { t: "when", all: ["goal1", "goal2", "goal3"], to: "converge" },
      {
        t: "choice",
        id: "hub",
        prompt: "亚父要走，叔父不语。你先开口——",
        hint: "可以选，也可以自己写一句。",
        options: [
          {
            label: "「亚父留步。今日之事，是籍错了。」",
            say: "亚父留步。今日之事，是籍错了。往后军中大计，先听亚父的。",
            hideIf: "goal1",
            next: "g1",
          },
          {
            label: "「叔父，出兵的消息，沛公是怎么知道的？」",
            say: "叔父，出兵的消息，沛公是怎么知道的？",
            hideIf: "goal2",
            next: "g2",
          },
          {
            label: "「樊哙问得好。有功之人，当裂土封侯。」",
            say: "樊哙那一问，籍今夜答他：有功之人，当裂土封侯。沛公先入关，籍不夺他的功。",
            proposedBy: "项伯",
            hideIf: "goal3",
            next: "g3",
          },
        ],
        free: {
          suggestions: [
            { text: "亚父，籍知错了，你别走。", hideIf: "goal1" },
            { text: "叔父，是不是你给张良报的信？", hideIf: "goal2" },
            { text: "樊哙说得对，有功之人就该封赏。", hideIf: "goal3" },
          ],
          // 按命中的关键词数取最贴近的一支，一样多时取靠前的。不收单字「王」「谁」：
          // 「大王」「项王」到处都是，「谁」也常出现在别的问题里
          routes: [
            {
              keywords: ["亚父", "范增", "认错", "错了", "知错", "别走", "留下", "留步", "不要走", "听你的", "赔罪", "骸骨"],
              next: "g1",
              hideIf: "goal1",
            },
            {
              keywords: ["叔父", "项伯", "报信", "报的信", "报了信", "走漏", "泄露", "消息", "昨夜", "那夜", "张良", "告密", "通风"],
              next: "g2",
              hideIf: "goal2",
            },
            {
              keywords: ["樊哙", "封侯", "封赏", "封他", "赏", "有功", "功劳", "论功", "关中", "汉王", "裂土", "那一问"],
              next: "g3",
              hideIf: "goal3",
            },
          ],
          fallback: "hub-miss",
        },
      },
    ],
    g1: [
      {
        t: "switch",
        key: "fate",
        cases: { origin: "g1-origin", nod: "g1-nod", pardon: "g1-pardon" },
        fallback: "g1-origin",
      },
    ],
    "g1-origin": [
      { t: "say", who: "范增", text: "大王今日，若肯应老臣一回……罢了。" },
      { t: "narrate", text: "他低头看着地上的碎玉，看了很久。" },
      { t: "say", who: "范增", text: "玉斗碎了，老臣还在。大王既然认了这个错，老臣就再留些时日。" },
      { t: "achieve", goal: 1 },
      { t: "goto", to: "hub" },
    ],
    "g1-nod": [
      { t: "say", who: "范增", text: "大王点了头，老臣以为大王想通了。原来只想通了一半。" },
      { t: "narrate", text: "他把剑插回鞘里，重重坐下。" },
      { t: "say", who: "范增", text: "也罢。下一回，大王别只点头。老臣不走了。" },
      { t: "achieve", goal: 1 },
      { t: "goto", to: "hub" },
    ],
    "g1-pardon": [
      { t: "say", who: "范增", text: "一笔勾销？大王勾销得了，沛公勾销不了。" },
      { t: "narrate", text: "他叹了口气，在案边坐了下来。" },
      { t: "say", who: "范增", text: "老臣不走。总得有人替大王记着这笔账。" },
      { t: "achieve", goal: 1 },
      { t: "goto", to: "hub" },
    ],
    g2: [{ t: "switch", key: "doubt", cases: { yes: "g2-doubt" }, fallback: "g2-plain" }],
    "g2-plain": [
      { t: "narrate", text: "项伯沉默了很久。" },
      {
        t: "say",
        who: "项伯",
        text: "……是我。那天夜里，我先去见了张良。他于我有活命之恩，我不忍看他和沛公一同死。",
      },
      { t: "say", who: "项伯", text: "沛公还与我约为婚姻。籍儿，叔父对不住你。" },
      { t: "narrate", text: "原来那一夜的消息，是从自己帐里走出去的。亚父冷笑了一声。" },
      { t: "achieve", goal: 2 },
      { t: "goto", to: "hub" },
    ],
    "g2-doubt": [
      { t: "say", who: "项伯", text: "那天夜里你就问过我，我没有说实话。" },
      { t: "say", who: "项伯", text: "……是我先去见了张良，把出兵的事告诉了他。沛公还与我约为婚姻。" },
      { t: "narrate", text: "亚父冷笑了一声。叔父低着头，再没有说话。" },
      { t: "achieve", goal: 2 },
      { t: "goto", to: "hub" },
    ],
    g3: [
      { t: "narrate", text: "帐中静了一静。" },
      { t: "say", who: "项伯", text: "樊哙那番话，满座无人能答。籍儿今夜答上了。" },
      { t: "say", who: "范增", text: "封侯可以，关中不能给他。巴、蜀道险，给他巴蜀、汉中，看他还走不走得出来。" },
      { t: "narrate", text: "史书里，沛公后来正是被封在巴蜀、汉中，做了汉王。" },
      { t: "achieve", goal: 3 },
      { t: "goto", to: "hub" },
    ],
    "hub-miss": [
      { t: "say", who: "范增", text: "大王还是想想，明日如何向诸侯交代罢。" },
      { t: "narrate", text: "亚父只是摇头。这一句，没有说到要紧处。" },
      { t: "goto", to: "hub" },
    ],

    // ── 收束与结局 ───────────────────────────────
    converge: [
      { t: "narrate", text: "那一夜，大帐里的灯一直亮到天明。" },
      {
        t: "switch",
        key: "fate",
        cases: { origin: "end-origin", nod: "end-nod", pardon: "end-pardon" },
        fallback: "end-origin",
      },
    ],
    "end-origin": [
      { t: "narrate", text: "天亮时，亚父把碎了的玉斗用布包好，收进行囊。他没有走。" },
      { t: "narrate", text: "课文里，项王「未有以应」。这一回，你答了。" },
      { t: "end", ending: "jade" },
    ],
    "end-nod": [
      { t: "narrate", text: "天还没亮，探马来报：霸上举火，沛公军连夜拔营。" },
      { t: "narrate", text: "你点过的那一下头，沛公记住了。楚汉之争，从这一夜开始。" },
      { t: "end", ending: "beacon" },
    ],
    "end-pardon": [
      { t: "narrate", text: "第二天，你派人把一封书信送到霸上：沛公有功，当封为王；鸿门之事，一笔勾销。" },
      { t: "narrate", text: "张良读完，对沛公说：项王此人，言而有信。" },
      { t: "end", ending: "promise" },
    ],
  },

  endings: [
    {
      id: "jade",
      title: "拾玉",
      art: "/demo/hongmen/end-jade.svg",
      lines: [
        "课文里，亚父撞破玉斗，说「竖子不足与谋」。",
        "这一夜你认了错，也答了樊哙那一问。玉斗拼不回去，亚父却留了下来。",
      ],
      teaser: "照着课文，默然不应。",
    },
    {
      id: "beacon",
      title: "霸上烽火",
      art: "/demo/hongmen/end-beacon.svg",
      lines: ["你点了头，项庄的剑却没能落下。", "沛公记住了那一剑。此后四年楚汉相争，从这一夜的烽火开始。"],
      teaser: "亚父举玦，你点了头。",
    },
    {
      id: "promise",
      title: "鸿门一诺",
      art: "/demo/hongmen/end-promise.svg",
      lines: [
        "你当着满座宾客说了一句「一笔勾销」，就一直认它。",
        "樊哙那一问，你给了回答。这一回，天下也许不必再打四年。",
      ],
      teaser: "亚父举玦，你向沛公举杯。",
    },
  ],

  seals: [
    { id: "restore", glyph: "还原", name: "还原", desc: "完整演完了课文里的鸿门一宴" },
    { id: "bond", glyph: "纳谏", name: "纳谏", desc: "续写目标全部达成" },
    { id: "rewrite", glyph: "改写", name: "改写", desc: "在举玦那一刻走出了课文之外的一条路" },
    { id: "parallel", glyph: "平行", name: "平行世界", desc: "回到抉择点，看了另一条路" },
    { id: "collect", glyph: "拾遗", name: "拾遗", desc: "拾齐了书匣里的全部原句" },
  ],
};
