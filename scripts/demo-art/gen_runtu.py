"""生成《少年闰土》演出台本的场景背景与结局图（矢量水墨风，1920x1080）。

用法：python3 scripts/demo-art/gen_runtu.py frontend/public/demo/runtu
随机元素（雪、瓜、星、贝壳）用固定种子，重跑结果不变。
"""
import math
import random
import sys

from ink import H, W, doc, eave, flying, lin, rad, ridge, snow, write_all


def bird(x, y, s=1.0, color="#1a1d22", back=None, flip=False):
    """一只低头啄食的小鸟。"""
    sx = -s if flip else s
    b = f'<g transform="translate({x} {y}) scale({sx} {s})">'
    b += f'<path d="M-26 -4 C -20 -22 8 -26 20 -12 C 26 -6 24 4 14 8 C 0 12 -18 10 -26 -4 Z" fill="{color}"/>'
    if back:
        b += f'<path d="M-20 -12 C -10 -22 8 -24 16 -14 C 6 -16 -8 -14 -20 -12 Z" fill="{back}"/>'
    b += f'<circle cx="22" cy="-2" r="8" fill="{color}"/>'
    b += '<path d="M28 0 L38 6 L28 5 Z" fill="#c99a3c"/>'
    b += f'<path d="M-26 -4 L-44 -14 L-40 2 Z" fill="{color}"/>'
    b += f'<path d="M-2 9 L-6 20 M6 9 L8 20" stroke="{color}" stroke-width="2.2"/>'
    b += "</g>"
    return b


def mati_wall(x, y_top, width, steps, step_h, color, cap="#14171c", direction=1):
    """马头墙：一级一级的阶梯山墙。"""
    out = ""
    seg = width / steps
    for i in range(steps):
        sx = x + (i * seg if direction > 0 else width - (i + 1) * seg)
        top = y_top + (steps - 1 - i) * step_h if direction > 0 else y_top + i * step_h
        top = y_top + i * step_h
        out += f'<rect x="{sx:.0f}" y="{top:.0f}" width="{seg + 1:.0f}" height="{H}" fill="{color}"/>'
        out += f'<path d="M{sx - 10:.0f} {top:.0f} L{sx + seg + 10:.0f} {top:.0f} L{sx + seg + 4:.0f} {top - 14:.0f} L{sx - 4:.0f} {top - 14:.0f} Z" fill="{cap}"/>'
        out += f'<path d="M{sx - 14:.0f} {top - 12:.0f} l -10 -10 l 8 0 Z M{sx + seg + 14:.0f} {top - 12:.0f} l 10 -10 l -8 0 Z" fill="{cap}"/>'
    return out


def lantern(x, y, s=1.0):
    return f'''<g transform="translate({x} {y}) scale({s})">
<circle r="120" fill="url(#lanternGlow)"/>
<line x1="0" y1="-70" x2="0" y2="-40" stroke="#2a1a12" stroke-width="3"/>
<rect x="-16" y="-44" width="32" height="8" rx="2" fill="#3a2414"/>
<ellipse rx="34" ry="40" fill="#c8402c"/>
<ellipse rx="34" ry="40" fill="url(#lanternShade)"/>
<path d="M-22 -30 Q -30 0 -22 30 M0 -40 L0 40 M22 -30 Q 30 0 22 30" stroke="#8a2a1c" stroke-width="2" fill="none" opacity="0.7"/>
<rect x="-14" y="36" width="28" height="8" rx="2" fill="#3a2414"/>
<path d="M-6 44 L-8 74 M0 44 L0 78 M6 44 L8 74" stroke="#d9a441" stroke-width="2.5"/>
</g>'''


# ── 1 正月初见：黄昏的老宅门口，红灯笼，细雪 ─────────────────────────
def newyear():
    rng = random.Random(1)
    defs = (
        lin("sky", [(0, "#151b2b", 1), (0.55, "#2c2f44", 1), (1, "#6a4436", 1)])
        + rad("lanternGlow", [(0, "#ff8a4c", 0.55), (0.4, "#ff6a3a", 0.18), (1, "#ff6a3a", 0)])
        + rad("lanternShade", [(0, "#ffd7a0", 0.75), (0.5, "#ff9a5a", 0.2), (1, "#5a1a10", 0.6)], cx=0.42, cy=0.38)
        + lin("door", [(0, "#f6c27a", 1), (1, "#b8743a", 1)])
        + rad("spill", [(0, "#f6b768", 0.5), (1, "#f6b768", 0)], cy=0.0, r=0.8)
        + lin("wall", [(0, "#3d4250", 1), (1, "#23262f", 1)])
        + lin("wallFar", [(0, "#2a2e3c", 1), (1, "#1c1f29", 1)])
    )
    b = f'<rect width="{W}" height="{H}" fill="url(#sky)"/>'
    b += '<circle cx="1530" cy="190" r="46" fill="#e9dcc0" opacity="0.5"/>'
    b += '<circle cx="1530" cy="190" r="120" fill="#e9dcc0" opacity="0.06"/>'
    # 远处的屋脊
    b += '<g filter="url(#inkSoft)" opacity="0.9">'
    b += mati_wall(-20, 380, 520, 3, 40, "url(#wallFar)")
    b += mati_wall(1380, 360, 560, 3, 44, "url(#wallFar)")
    b += "</g>"
    b += f'<path d="M420 470 Q 700 430 980 450 Q 1200 440 1440 470 L1440 {H} L420 {H} Z" fill="#1d212b"/>'
    b += eave(380, 470, 1480, 470, 22)
    # 主墙
    b += f'<rect x="0" y="560" width="{W}" height="{H - 560}" fill="url(#wall)"/>'
    b += eave(-20, 548, W + 20, 548, 26)
    # 墙上的水渍
    for x in (180, 420, 1500, 1720):
        b += f'<path d="M{x} 590 q 20 120 -6 260 q 30 -80 40 -260 Z" fill="#1a1d24" opacity="0.35" filter="url(#blur6)"/>'
    # 门楼
    b += '<path d="M700 640 Q 960 600 1220 640 L1250 618 Q 960 560 670 618 Z" fill="#101318"/>'
    b += eave(720, 640, 1200, 640, 18)
    b += '<rect x="800" y="660" width="320" height="420" fill="#16191f"/>'
    b += '<rect x="846" y="700" width="228" height="380" fill="url(#door)"/>'
    b += '<rect x="846" y="700" width="228" height="380" fill="#000" opacity="0.08"/>'
    # 门里：供桌与烛光
    b += '<rect x="880" y="900" width="160" height="16" fill="#3a2414"/>'
    b += '<rect x="890" y="916" width="10" height="164" fill="#3a2414"/><rect x="1020" y="916" width="10" height="164" fill="#3a2414"/>'
    for cx in (920, 1000):
        b += f'<rect x="{cx - 5}" y="860" width="10" height="40" fill="#d8402c"/><ellipse cx="{cx}" cy="852" rx="5" ry="10" fill="#fff2c4"/>'
        b += f'<circle cx="{cx}" cy="852" r="30" fill="#fff2c4" opacity="0.25" filter="url(#blur6)"/>'
    b += '<path d="M960 896 q -10 -60 6 -110 q 12 -40 -4 -80" stroke="#f3e6cf" stroke-width="3" fill="none" opacity="0.35" filter="url(#blur6)"/>'
    # 春联
    b += '<rect x="812" y="712" width="26" height="250" fill="#a32b20"/><rect x="1082" y="712" width="26" height="250" fill="#a32b20"/>'
    b += '<rect x="880" y="672" width="160" height="22" fill="#a32b20"/>'
    # 门槛与台阶
    b += '<rect x="780" y="1040" width="360" height="40" fill="#1b1e24"/>'
    b += '<ellipse cx="960" cy="1080" rx="520" ry="120" fill="url(#spill)"/>'
    b += lantern(740, 760) + lantern(1180, 760)
    b += snow(rng, 160, rmax=3.2, opacity=(0.25, 0.75))
    return doc(b, defs)


# ── 2 雪地捕鸟：雪地上支起的竹匾，几只鸟在啄秕谷 ─────────────────────
def snow_scene():
    rng = random.Random(2)
    defs = (
        lin("sky", [(0, "#39424f", 1), (1, "#7d8793", 1)])
        + lin("ground", [(0, "#a9b3bc", 1), (1, "#6f7984", 1)])
        + rad("sieve", [(0, "#c49a5c", 1), (0.7, "#9a7440", 1), (1, "#6a4c26", 1)])
        + rad("sieveShadow", [(0, "#2b323b", 0.55), (1, "#2b323b", 0)])
    )
    b = f'<rect width="{W}" height="{H}" fill="url(#sky)"/>'
    b += f'<path d="{ridge(rng, 520, 30, 220)}" fill="#59636f" filter="url(#ink)" opacity="0.8"/>'
    # 远处一排枯树
    for i in range(22):
        x = rng.uniform(0, W)
        h = rng.uniform(60, 140)
        b += f'<path d="M{x:.0f} 560 l {rng.uniform(-6, 6):.0f} {-h:.0f}" stroke="#3a424c" stroke-width="{rng.uniform(2, 4):.1f}" opacity="0.7"/>'
        for _ in range(3):
            t = rng.uniform(0.3, 0.9)
            b += f'<path d="M{x:.0f} {560 - h * t:.0f} l {rng.uniform(-30, 30):.0f} {-rng.uniform(15, 40):.0f}" stroke="#3a424c" stroke-width="1.6" opacity="0.6"/>'
    b += f'<path d="M-20 600 Q 480 560 960 590 T 1940 580 L1940 {H} L-20 {H} Z" fill="url(#ground)"/>'
    # 扫开的一块空地
    b += '<ellipse cx="900" cy="860" rx="420" ry="120" fill="#5d5245" opacity="0.55" filter="url(#blur18)"/>'
    for _ in range(90):
        x, y = rng.uniform(560, 1240), rng.uniform(790, 930)
        b += f'<ellipse cx="{x:.0f}" cy="{y:.0f}" rx="3" ry="2" fill="#d8b46a" opacity="0.8"/>'
    # 竹匾：一边着地，一边用短棒支起
    b += '<ellipse cx="900" cy="880" rx="250" ry="50" fill="url(#sieveShadow)"/>'
    b += '<g transform="translate(900 760) rotate(-14)">'
    b += '<ellipse rx="230" ry="78" fill="url(#sieve)"/>'
    for r in range(24, 230, 22):
        b += f'<ellipse rx="{r}" ry="{r * 78 / 230:.0f}" fill="none" stroke="#6a4c26" stroke-width="2" opacity="0.5"/>'
    b += '<ellipse rx="230" ry="78" fill="none" stroke="#5a3e1c" stroke-width="9"/>'
    b += '<ellipse rx="210" ry="66" fill="#000" opacity="0.14"/>'
    b += "</g>"
    b += '<path d="M780 878 L 812 772" stroke="#5a3e1c" stroke-width="9" stroke-linecap="round"/>'
    # 缚在棒上的绳子，一直拖到画外
    b += '<path d="M800 812 C 1000 900 1300 860 1500 900 S 1800 960 1960 930" stroke="#3c2a16" stroke-width="3" fill="none"/>'
    # 鸟：稻鸡、角鸡、鹁鸪、蓝背
    b += bird(1080, 880, 1.25, "#5b4632", "#8a6a44")
    b += bird(1170, 900, 1.1, "#3d3a38", "#b84a2c", flip=True)
    b += bird(640, 900, 1.15, "#4c4f56", "#6d7b8c", flip=True)
    b += bird(1300, 870, 1.0, "#2e3644", "#3f78b8")
    # 脚印
    for i in range(10):
        x = 1350 + i * 60
        y = 990 - i * 6 + (12 if i % 2 else 0)
        b += f'<ellipse cx="{x}" cy="{y}" rx="11" ry="6" fill="#535d68" opacity="0.6"/>'
    b += snow(rng, 260, rmax=4.6, opacity=(0.4, 0.95))
    return doc(b, defs)


# ── 3 月下刺猹：深蓝的天、金黄的圆月、碧绿的西瓜地、少年与猹 ─────────────
def moon():
    rng = random.Random(3)
    defs = (
        lin("sky", [(0, "#06101f", 1), (0.6, "#0f2547", 1), (1, "#1d3d68", 1)])
        + rad("moonGlow", [(0, "#ffd98a", 0.55), (0.35, "#ffc960", 0.16), (1, "#ffc960", 0)])
        + rad("moonFace", [(0, "#fff0b8", 1), (0.75, "#f7cf6c", 1), (1, "#e3a943", 1)], cx=0.42, cy=0.4)
        + lin("sea", [(0, "#0b1d36", 1), (1, "#081426", 1)])
        + lin("sand", [(0, "#14243a", 1), (1, "#0a1220", 1)])
        + rad("melon", [(0, "#4f9a5a", 1), (0.7, "#24603a", 1), (1, "#123a22", 1)], cx=0.38, cy=0.32)
    )
    b = f'<rect width="{W}" height="{H}" fill="url(#sky)"/>'
    for _ in range(90):
        x, y = rng.uniform(0, W), rng.uniform(0, 520)
        b += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rng.uniform(0.6, 1.8):.1f}" fill="#dfe8ff" opacity="{rng.uniform(0.2, 0.8):.2f}"/>'
    b += '<circle cx="1360" cy="290" r="420" fill="url(#moonGlow)"/>'
    b += '<circle cx="1360" cy="290" r="168" fill="url(#moonFace)"/>'
    for cx, cy, r in ((1310, 250, 26), (1410, 330, 18), (1380, 220, 12), (1300, 340, 14)):
        b += f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#d9a447" opacity="0.28"/>'
    # 海与月光
    b += f'<rect y="590" width="{W}" height="90" fill="url(#sea)"/>'
    for _ in range(70):
        y = rng.uniform(596, 676)
        w = rng.uniform(12, 70) * (1 - (y - 596) / 160)
        x = 1360 + rng.gauss(0, 60 + (y - 596) * 1.2)
        b += f'<rect x="{x - w / 2:.0f}" y="{y:.0f}" width="{w:.0f}" height="2" fill="#ffd98a" opacity="{rng.uniform(0.3, 0.8):.2f}"/>'
    # 沙地
    b += f'<path d="M-20 660 Q 600 640 1100 652 T 1940 648 L1940 {H} L-20 {H} Z" fill="url(#sand)"/>'
    # 一望无际的西瓜：一行行往近处排，越近越大
    rows = []
    y = 690
    while y < H + 60:
        rows.append(y)
        y += 14 + (y - 680) * 0.16
    for y in rows:
        s = 0.18 + (y - 680) / 380
        step = 150 * s
        x = rng.uniform(-step, 0)
        while x < W + step:
            if not (460 < x < 860 and y > 760 and y < 940):
                rx, ry = 46 * s, 32 * s
                jx = x + rng.uniform(-step * 0.3, step * 0.3)
                b += f'<ellipse cx="{jx:.0f}" cy="{y:.0f}" rx="{rx:.1f}" ry="{ry:.1f}" fill="url(#melon)"/>'
                for k in (-0.5, 0, 0.5):
                    b += f'<path d="M{jx + k * rx:.0f} {y - ry * 0.95:.0f} Q {jx + k * rx * 1.4:.0f} {y:.0f} {jx + k * rx:.0f} {y + ry * 0.95:.0f}" stroke="#0e2a18" stroke-width="{max(1, 3 * s):.1f}" fill="none" opacity="0.6"/>'
                b += f'<path d="M{jx - rx * 0.9:.0f} {y - ry * 0.4:.0f} q {-rx * 0.8:.0f} {-ry * 0.9:.0f} {-rx * 1.4:.0f} {-ry * 0.2:.0f} q {rx * 0.5:.0f} {ry * 0.6:.0f} {rx * 1.4:.0f} {ry * 0.2:.0f} Z" fill="#1b4a2a" opacity="0.85"/>'
            x += step * rng.uniform(0.85, 1.25)
    # 少年：项带银圈，手捏钢叉，向猹尽力刺去
    k = "#060a12"
    b += '<g transform="translate(600 900) scale(1.05)">'
    b += '<ellipse cx="40" cy="6" rx="130" ry="14" fill="#000" opacity="0.35"/>'
    b += f'<path d="M-46 0 L-14 -92" stroke="{k}" stroke-width="20" stroke-linecap="round"/>'
    b += f'<path d="M62 0 L44 -50 L12 -92" stroke="{k}" stroke-width="20" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
    b += f'<path d="M-24 -86 L 30 -100 L 52 -168 L 6 -170 Z" fill="{k}"/>'
    b += f'<path d="M40 -160 L 96 -128 L 132 -122" stroke="{k}" stroke-width="15" stroke-linecap="round" fill="none"/>'
    b += f'<path d="M20 -160 L 70 -116 L 110 -104" stroke="{k}" stroke-width="15" stroke-linecap="round" fill="none"/>'
    b += f'<circle cx="44" cy="-192" r="21" fill="{k}"/>'
    b += f'<path d="M22 -198 Q 44 -224 68 -200 Z" fill="{k}"/>'
    b += '<ellipse cx="38" cy="-170" rx="17" ry="6" fill="none" stroke="#e9eef8" stroke-width="3.5"/>'
    b += '<path d="M24 -192 Q 44 -214 64 -194" stroke="#ffd98a" stroke-width="2" fill="none" opacity="0.6"/>'
    b += f'<path d="M-30 -186 L 236 -26" stroke="{k}" stroke-width="6" stroke-linecap="round"/>'
    b += f'<path d="M222 -46 L 252 -16 M230 -34 L 246 -2 M236 -26 L 262 -28" stroke="{k}" stroke-width="5" stroke-linecap="round"/>'
    b += "</g>"
    # 猹：将身一扭
    b += '<g transform="translate(900 902) rotate(-12)">'
    b += f'<ellipse rx="54" ry="22" fill="{k}"/><ellipse cx="54" cy="-8" rx="20" ry="13" fill="{k}"/>'
    b += f'<path d="M70 -10 L 86 -4 L 70 0 Z" fill="{k}"/><path d="M-50 -4 Q -86 -26 -104 -8" stroke="{k}" stroke-width="9" stroke-linecap="round" fill="none"/>'
    b += f'<path d="M-30 14 L-38 34 M-6 18 L-2 36 M24 16 L 34 34 M40 12 L 52 28" stroke="{k}" stroke-width="7" stroke-linecap="round"/>'
    b += '<path d="M-40 -14 Q 0 -30 44 -18" stroke="#ffd98a" stroke-width="2.5" fill="none" opacity="0.55"/>'
    b += "</g>"
    return doc(b, defs)


# ── 4 四角的天空：高墙围出的天井，抬头只有一方天 ─────────────────────
def courtyard(sky_stops, wall_tint, birds_color, birds_n, glow, seed):
    rng = random.Random(seed)
    vx = 960
    defs = (
        lin("sky", sky_stops)
        + lin("wallL", [(0, wall_tint[0], 1), (1, wall_tint[1], 1)], x2=1, y2=0)
        + lin("wallR", [(0, wall_tint[1], 1), (1, wall_tint[0], 1)], x2=1, y2=0)
        + lin("wallB", [(0, wall_tint[2], 1), (1, wall_tint[1], 1)])
        + lin("floor", [(0, "#24282f", 1), (1, "#121419", 1)])
        + rad("skyGlow", [(0, glow, 0.45), (1, glow, 0)])
    )
    b = f'<rect width="{W}" height="{H}" fill="url(#sky)"/>'
    b += '<ellipse cx="960" cy="120" rx="520" ry="260" fill="url(#skyGlow)"/>'
    for _ in range(6):
        cx, cy = rng.uniform(560, 1360), rng.uniform(60, 220)
        b += f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{rng.uniform(90, 200):.0f}" ry="{rng.uniform(16, 34):.0f}" fill="#ffffff" opacity="{rng.uniform(0.12, 0.3):.2f}" filter="url(#blur18)"/>'
    for i in range(birds_n):
        b += flying(rng.uniform(700, 1240), rng.uniform(70, 230), rng.uniform(0.5, 1.0), birds_color)
    bx0, bx1, by0, by1 = 620, 1300, 330, 880
    b += f'<path d="M0 0 L{bx0} {by0} L{bx0} {by1} L0 {H} Z" fill="url(#wallL)"/>'
    b += f'<path d="M{W} 0 L{bx1} {by0} L{bx1} {by1} L{W} {H} Z" fill="url(#wallR)"/>'
    b += f'<rect x="{bx0}" y="{by0}" width="{bx1 - bx0}" height="{by1 - by0}" fill="url(#wallB)"/>'
    b += f'<path d="M0 {H} L{bx0} {by1} L{bx1} {by1} L{W} {H} Z" fill="url(#floor)"/>'
    # 地砖缝
    for i in range(-8, 9):
        x = 960 + i * 160
        b += f'<path d="M{vx + (x - vx) * 0.38:.0f} {by1} L{x * 1.6 - 960 * 0.6:.0f} {H}" stroke="#0b0d10" stroke-width="2" opacity="0.6"/>'
    for t in (0.18, 0.4, 0.68):
        y = by1 + (H - by1) * t
        b += f'<path d="M0 {y:.0f} L{W} {y:.0f}" stroke="#0b0d10" stroke-width="2" opacity="0.5"/>'
    # 墙上的斑驳
    for _ in range(14):
        x, y = rng.uniform(40, 1880), rng.uniform(340, 860)
        b += f'<ellipse cx="{x:.0f}" cy="{y:.0f}" rx="{rng.uniform(30, 90):.0f}" ry="{rng.uniform(40, 140):.0f}" fill="#0e1014" opacity="0.22" filter="url(#blur18)"/>'
    # 后墙顶上的马头墙：两级台阶，墙头压着黑瓦
    for x0, x1, top in ((bx0 + 60, bx1 - 60, by0 - 70), (bx0 + 200, bx1 - 200, by0 - 130)):
        b += f'<rect x="{x0}" y="{top}" width="{x1 - x0}" height="{by0 - top + 2}" fill="{wall_tint[2]}"/>'
        b += f'<rect x="{x0}" y="{top}" width="{x1 - x0}" height="{by0 - top + 2}" fill="#000" opacity="0.12"/>'
        b += eave(x0 - 16, top - 16, x1 + 16, top - 16, 18, color="#101216")
        b += f'<path d="M{x0 - 22} {top - 14} l -16 -16 l 12 0 Z M{x1 + 22} {top - 14} l 16 -16 l -12 0 Z" fill="#101216"/>'
    # 檐口：三面墙的顶边，斜着的两条也排上瓦当
    b += eave(-40, -18, bx0 + 10, by0 - 14, 30, color="#101216")
    b += eave(W + 40, -18, bx1 - 10, by0 - 14, 30, color="#101216")
    b += eave(bx0 - 20, by0 - 12, bx1 + 20, by0 - 12, 28, color="#101216")
    # 侧墙上的花窗
    b += '<path d="M190 380 L 420 470 L 420 640 L 190 600 Z" fill="#14171c"/>'
    for i in range(1, 6):
        t = i / 6
        x = 190 + 230 * t
        b += f'<path d="M{x:.0f} {380 + 90 * t:.0f} L{x:.0f} {600 + 40 * t:.0f}" stroke="#3a3f48" stroke-width="3"/>'
    for i in range(1, 5):
        t = i / 5
        b += f'<path d="M190 {380 + 220 * t:.0f} L420 {470 + 170 * t:.0f}" stroke="#3a3f48" stroke-width="3"/>'
    # 水缸
    b += '<ellipse cx="300" cy="1010" rx="150" ry="34" fill="#0a0c0f" opacity="0.6"/>'
    b += '<path d="M170 880 Q 160 1000 230 1020 L 370 1020 Q 440 1000 430 880 Z" fill="#2a2620"/>'
    b += '<ellipse cx="300" cy="880" rx="130" ry="28" fill="#1a1814"/><ellipse cx="300" cy="882" rx="112" ry="20" fill="#3d4a5c" opacity="0.7"/>'
    return b, defs


def sky_scene():
    b, defs = courtyard(
        [(0, "#5f9bd0", 1), (1, "#bcdcef", 1)],
        ("#2b2f36", "#4a4f57", "#5a5f67"),
        "#1f2a36",
        5,
        "#ffffff",
        4,
    )
    return doc(b, defs)


# ── 5 正月离别：清晨的河埠头，乌篷船解了缆 ─────────────────────────
def farewell():
    rng = random.Random(5)
    defs = (
        lin("sky", [(0, "#232c44", 1), (0.55, "#6c6577", 1), (1, "#d3a283", 1)])
        + lin("river", [(0, "#8b7f86", 1), (0.3, "#4b4a5a", 1), (1, "#1c2030", 1)])
        + lin("mist", [(0, "#e8dcd4", 0), (0.5, "#e8dcd4", 0.35), (1, "#e8dcd4", 0)])
        + rad("sun", [(0, "#ffd2a0", 0.8), (0.4, "#ffb47a", 0.25), (1, "#ffb47a", 0)])
    )
    b = f'<rect width="{W}" height="{H}" fill="url(#sky)"/>'
    b += '<circle cx="1180" cy="520" r="300" fill="url(#sun)"/>'
    b += f'<path d="{ridge(rng, 470, 40, 260)}" fill="#4a4656" opacity="0.65" filter="url(#ink)"/>'
    # 对岸的人家
    for x in range(120, 1900, 150):
        if rng.random() < 0.7:
            w = rng.uniform(70, 120)
            h = rng.uniform(40, 70)
            y = 540 + rng.uniform(-8, 8)
            b += f'<rect x="{x:.0f}" y="{y - h:.0f}" width="{w:.0f}" height="{h + 20:.0f}" fill="#3a3746" opacity="0.8"/>'
            b += f'<path d="M{x - 10:.0f} {y - h:.0f} L{x + w / 2:.0f} {y - h - 26:.0f} L{x + w + 10:.0f} {y - h:.0f} Z" fill="#26242f" opacity="0.85"/>'
    b += f'<rect y="560" width="{W}" height="{H - 560}" fill="url(#river)"/>'
    for _ in range(80):
        y = rng.uniform(570, 1060)
        w = rng.uniform(30, 160)
        x = rng.uniform(0, W)
        b += f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="2" fill="#f2d2b0" opacity="{rng.uniform(0.08, 0.35):.2f}"/>'
    b += f'<rect y="520" width="{W}" height="120" fill="url(#mist)" filter="url(#blur18)"/>'
    # 乌篷船
    b += '<g transform="translate(1320 760)">'
    b += '<ellipse cx="0" cy="40" rx="330" ry="22" fill="#0b0d14" opacity="0.4"/>'
    b += '<path d="M-330 -6 Q -300 30 -200 38 L 220 38 Q 320 30 350 -16 Q 250 8 0 8 Q -200 8 -330 -6 Z" fill="#14161c"/>'
    for i, x in enumerate((-150, -40, 70)):
        b += f'<path d="M{x - 60} 6 Q {x} -88 {x + 60} 6 Z" fill="#0d0e12"/>'
        b += f'<path d="M{x - 50} 0 Q {x} -70 {x + 50} 0" stroke="#2a2c34" stroke-width="3" fill="none"/>'
    # 撑船的人（忙月）与竹篙
    b += '<path d="M230 8 L 236 -70" stroke="#0d0e12" stroke-width="16" stroke-linecap="round"/>'
    b += '<circle cx="238" cy="-88" r="13" fill="#0d0e12"/><path d="M220 -94 Q 238 -116 258 -94 Z" fill="#0d0e12"/>'
    b += '<path d="M250 -64 L 320 -170 M 238 -50 L 180 120" stroke="#2a2016" stroke-width="5" stroke-linecap="round"/>'
    b += "</g>"
    # 缆绳从船头拖到埠头
    b += '<path d="M1000 760 Q 760 820 520 830" stroke="#2a2016" stroke-width="3" fill="none"/>'
    # 河埠头石阶
    for i in range(6):
        y = 780 + i * 52
        x1 = 560 - i * 40
        b += f'<path d="M-40 {y} L{x1} {y} L{x1 + 30} {y + 52} L-40 {y + 52} Z" fill="#{"3a3d46" if i % 2 else "2f3239"}"/>'
        b += f'<path d="M-40 {y} L{x1} {y}" stroke="#5b5f6a" stroke-width="2" opacity="0.6"/>'
    # 岸边的柳
    b += '<path d="M180 790 C 170 600 230 430 200 240" stroke="#1a1712" stroke-width="22" fill="none" stroke-linecap="round"/>'
    for i in range(26):
        x0 = 200 + rng.uniform(-60, 70)
        y0 = rng.uniform(240, 420)
        length = rng.uniform(160, 360)
        b += f'<path d="M{x0:.0f} {y0:.0f} q {rng.uniform(20, 90):.0f} {length * 0.4:.0f} {rng.uniform(40, 160):.0f} {length:.0f}" stroke="#1d1b16" stroke-width="{rng.uniform(1.2, 2.6):.1f}" fill="none" opacity="0.8"/>'
    b += f'<rect y="840" width="{W}" height="200" fill="url(#mist)" opacity="0.6" filter="url(#blur40)"/>'
    return doc(b, defs)


# ── 6 二十年后：苍黄的天底下，几个萧索的荒村 ─────────────────────────
def ret():
    rng = random.Random(6)
    defs = (
        lin("sky", [(0, "#2d2a24", 1), (0.6, "#5e5642", 1), (1, "#8a7d5c", 1)])
        + lin("land", [(0, "#4a4434", 1), (1, "#1c1a15", 1)])
    )
    b = f'<rect width="{W}" height="{H}" fill="url(#sky)"/>'
    for _ in range(14):
        y = rng.uniform(80, 520)
        b += f'<path d="M{rng.uniform(-200, W):.0f} {y:.0f} q 300 {rng.uniform(-20, 20):.0f} 700 0" stroke="#c9b98e" stroke-width="{rng.uniform(1, 3):.1f}" opacity="0.18" fill="none" filter="url(#blur6)"/>'
    b += f'<path d="{ridge(rng, 600, 18, 300)}" fill="#3f3a2e" filter="url(#ink)"/>'
    # 远近横着几个荒村
    for cx, scale in ((300, 0.7), (980, 0.55), (1560, 0.8)):
        for j in range(rng.randint(3, 5)):
            x = cx + j * 90 * scale + rng.uniform(-20, 20)
            y = 610 + rng.uniform(-6, 10)
            w, h = 80 * scale, 46 * scale
            b += f'<rect x="{x:.0f}" y="{y - h:.0f}" width="{w:.0f}" height="{h:.0f}" fill="#24211b"/>'
            b += f'<path d="M{x - 8 * scale:.0f} {y - h:.0f} Q{x + w / 2:.0f} {y - h - 40 * scale:.0f} {x + w + 8 * scale:.0f} {y - h:.0f} Z" fill="#191712"/>'
        b += f'<path d="M{cx + 40:.0f} {600 - 60 * scale:.0f} q -20 -60 10 -120 q 20 -50 -10 -100" stroke="#9a8e72" stroke-width="5" fill="none" opacity="0.25" filter="url(#blur6)"/>'
        for _ in range(4):
            x = cx + rng.uniform(-80, 320 * scale)
            h = rng.uniform(80, 150) * scale
            b += f'<path d="M{x:.0f} 615 l 0 {-h:.0f}" stroke="#15130f" stroke-width="3"/>'
            for _ in range(4):
                t = rng.uniform(0.3, 0.95)
                b += f'<path d="M{x:.0f} {615 - h * t:.0f} l {rng.uniform(-36, 36):.0f} {-rng.uniform(14, 40):.0f}" stroke="#15130f" stroke-width="1.6"/>'
    b += f'<path d="M-20 640 Q 700 620 1300 636 T 1940 630 L1940 {H} L-20 {H} Z" fill="url(#land)"/>'
    # 小路
    b += '<path d="M760 1080 C 820 900 940 760 1000 640 L 1016 640 C 980 760 900 900 980 1080 Z" fill="#5a523e" opacity="0.5"/>'
    # 枯草，被风压向一边
    for _ in range(420):
        x = rng.uniform(-20, W + 20)
        y = rng.uniform(700, H + 20)
        s = 0.4 + (y - 700) / 380
        h = rng.uniform(30, 90) * s
        lean = rng.uniform(20, 60) * s
        col = rng.choice(("#2a2519", "#3b3423", "#6b5e3e", "#1b1810"))
        b += f'<path d="M{x:.0f} {y:.0f} q {lean * 0.2:.0f} {-h * 0.6:.0f} {lean:.0f} {-h:.0f}" stroke="{col}" stroke-width="{max(1, 2.6 * s):.1f}" fill="none" opacity="0.85"/>'
    # 半截篱笆
    for i in range(8):
        x = 1460 + i * 46
        b += f'<path d="M{x} 900 l {rng.uniform(-6, 6):.0f} -{rng.uniform(70, 120):.0f}" stroke="#1d1a13" stroke-width="7" stroke-linecap="round"/>'
    b += '<path d="M1440 840 L 1800 830 M1440 870 L 1800 866" stroke="#1d1a13" stroke-width="4"/>'
    b += snow(rng, 60, color="#d8cfb4", rmin=1, rmax=2.6, opacity=(0.15, 0.45))
    return doc(b, defs)


# ── 结局 · 一包贝壳 ─────────────────────────────────────────────
def shell(rng, x, y, s, kind, color):
    rot = rng.uniform(-40, 40)
    out = f'<g transform="translate({x:.0f} {y:.0f}) rotate({rot:.0f}) scale({s:.2f})">'
    out += '<ellipse cx="4" cy="10" rx="40" ry="12" fill="#000" opacity="0.35"/>'
    if kind == "fan":
        out += f'<path d="M0 26 L-40 -14 Q 0 -44 40 -14 Z" fill="{color}"/>'
        for a in range(-36, 37, 9):
            r = math.radians(a - 90)
            out += f'<path d="M0 26 L{40 * math.cos(r):.1f} {-14 + 40 * math.sin(r) * 0.75:.1f}" stroke="#000" stroke-opacity="0.22" stroke-width="2"/>'
        out += '<path d="M-10 26 h 20 l -4 8 h -12 Z" fill="#000" opacity="0.2"/>'
    elif kind == "spiral":
        out += f'<path d="M-30 10 Q -34 -26 0 -32 Q 30 -30 34 0 Q 30 18 0 22 Q -18 22 -30 10 Z" fill="{color}"/>'
        out += '<path d="M24 -2 Q 18 -20 0 -20 Q -16 -18 -16 0 Q -12 12 2 10 Q 12 6 8 -4" stroke="#000" stroke-opacity="0.3" stroke-width="3" fill="none"/>'
    else:  # 观音手 / 鬼见怕：带刺的长贝
        out += f'<path d="M-38 6 Q -20 -22 30 -14 Q 44 -4 30 10 Q -10 22 -38 6 Z" fill="{color}"/>'
        for i in range(5):
            out += f'<path d="M{-24 + i * 12} {-12 + i * 0.5} l 4 -14 l 4 13 Z" fill="{color}"/>'
        out += '<path d="M-30 6 Q 0 -2 30 0" stroke="#000" stroke-opacity="0.25" stroke-width="2" fill="none"/>'
    out += '<path d="M-20 -10 Q -6 -22 12 -16" stroke="#fff" stroke-opacity="0.35" stroke-width="3" fill="none"/>'
    out += "</g>"
    return out


def end_shells():
    rng = random.Random(7)
    defs = (
        lin("table", [(0, "#2a1d14", 1), (1, "#120c08", 1)])
        + rad("lamp", [(0, "#ffcf8a", 0.42), (0.5, "#ffb060", 0.1), (1, "#ffb060", 0)])
        + lin("cloth", [(0, "#d9c7a4", 1), (1, "#b49e78", 1)])
    )
    b = f'<rect width="{W}" height="{H}" fill="url(#table)"/>'
    for i in range(14):
        y = i * 80 + rng.uniform(-6, 6)
        b += f'<path d="M0 {y:.0f} Q 960 {y + rng.uniform(-20, 20):.0f} 1920 {y:.0f}" stroke="#000" stroke-width="2" opacity="0.22" fill="none"/>'
    b += '<circle cx="1280" cy="520" r="760" fill="url(#lamp)"/>'
    # 摊开的包袱布
    b += '<path d="M820 360 Q 1300 300 1760 380 Q 1820 640 1740 900 Q 1300 960 860 900 Q 780 640 820 360 Z" fill="url(#cloth)" opacity="0.92" filter="url(#inkSoft)"/>'
    # 半露的《花镜》
    b += '<g transform="translate(1520 300) rotate(12)"><rect x="-150" y="-100" width="300" height="200" fill="#3c4a3a"/><rect x="-140" y="-92" width="280" height="184" fill="#e3d6b8"/>'
    b += '<path d="M0 -92 V 92" stroke="#3c4a3a" stroke-width="4"/>'
    b += '<path d="M-110 30 q 30 -70 80 -40 M -90 -20 q 10 -20 30 -10" stroke="#5a6a4a" stroke-width="3" fill="none"/>'
    b += flying(70, -30, 1.3, "#5a3a24", 0.8) + flying(100, 10, 0.9, "#5a3a24", 0.7)
    b += '<rect x="-128" y="-80" width="22" height="80" fill="#a32b20" opacity="0.85"/></g>'
    # 鸟毛
    for x, y, rot, col in ((980, 520, -30, "#3f78b8"), (1060, 470, -50, "#c8932e"), (1640, 760, 20, "#7b4a2a")):
        b += f'<g transform="translate({x} {y}) rotate({rot})"><path d="M0 0 Q 30 -90 0 -220 Q -30 -90 0 0 Z" fill="{col}" opacity="0.9"/><path d="M0 0 V -220" stroke="#f2e6cc" stroke-width="2"/></g>'
    colors = ["#d8573c", "#e07a5f", "#5aa07a", "#7cc2a0", "#e8c7a0", "#f0dcc0", "#c34a3a", "#86b7c9", "#d9a441"]
    for _ in range(46):
        x = rng.gauss(1290, 220)
        y = rng.gauss(640, 120)
        if not (860 < x < 1760 and 380 < y < 900):
            continue
        b += shell(rng, x, y, rng.uniform(0.7, 1.4), rng.choice(("fan", "fan", "spiral", "spiky")), rng.choice(colors))
    return doc(b, defs)


# ── 结局 · 海边的路 ─────────────────────────────────────────────
def end_road():
    rng = random.Random(8)
    defs = (
        lin("sky", [(0, "#0d1a33", 1), (0.6, "#33496e", 1), (1, "#d6a77a", 1)])
        + lin("sea", [(0, "#36506e", 1), (1, "#16243a", 1)])
        + lin("sand", [(0, "#8d7a5e", 1), (1, "#3a3022", 1)])
        + rad("moonGlow", [(0, "#ffe2a8", 0.6), (1, "#ffe2a8", 0)])
    )
    b = f'<rect width="{W}" height="{H}" fill="url(#sky)"/>'
    for _ in range(60):
        b += f'<circle cx="{rng.uniform(0, W):.0f}" cy="{rng.uniform(0, 380):.0f}" r="{rng.uniform(0.6, 1.6):.1f}" fill="#fff" opacity="{rng.uniform(0.2, 0.7):.2f}"/>'
    b += '<circle cx="1500" cy="470" r="240" fill="url(#moonGlow)"/><circle cx="1500" cy="470" r="70" fill="#ffe7b4"/>'
    b += f'<path d="M760 540 L{W} 520 L{W} 760 Q 1400 700 760 560 Z" fill="url(#sea)"/>'
    for _ in range(50):
        y = rng.uniform(546, 720)
        x = rng.uniform(1100, 1900)
        b += f'<rect x="{x:.0f}" y="{y:.0f}" width="{rng.uniform(20, 90):.0f}" height="2" fill="#ffe2a8" opacity="{rng.uniform(0.2, 0.6):.2f}"/>'
    b += f'<path d="M-20 540 L 760 540 Q 1400 700 {W + 20} 780 L{W + 20} {H} L-20 {H} Z" fill="url(#sand)"/>'
    b += f'<path d="M760 556 Q 1400 708 {W + 20} 790" stroke="#f3e6cf" stroke-width="5" fill="none" opacity="0.6" filter="url(#blur6)"/>'
    # 两行脚印，从近处一直走到远处的两个人那里
    for line, dx in ((0, -26), (1, 26)):
        for i in range(26):
            t = i / 25
            x = 560 + (1120 - 560) * t + dx * (1 - t * 0.85) + (8 if i % 2 else -8) * (1 - t)
            y = 1060 - (1060 - 640) * (t ** 0.8)
            s = 1 - t * 0.85
            b += f'<ellipse cx="{x:.0f}" cy="{y:.0f}" rx="{10 * s:.1f}" ry="{5 * s:.1f}" fill="#2e261b" opacity="{0.7 - t * 0.4:.2f}"/>'
    # 远处并肩走着的两个人
    for x, h in ((1118, 54), (1150, 58)):
        b += f'<path d="M{x} 640 l -5 -{h * 0.45:.0f} M{x} 640 l 5 -{h * 0.45:.0f}" stroke="#14110c" stroke-width="5" stroke-linecap="round"/>'
        b += f'<path d="M{x - 7} {640 - h * 0.42:.0f} L{x + 7} {640 - h * 0.42:.0f} L{x + 5} {640 - h * 0.85:.0f} L{x - 5} {640 - h * 0.85:.0f} Z" fill="#14110c"/>'
        b += f'<circle cx="{x}" cy="{640 - h:.0f}" r="7" fill="#14110c"/>'
    b += snow(rng, 0)
    return doc(b, defs)


def end_sky():
    b, defs = courtyard(
        [(0, "#2a2448", 1), (0.6, "#b0607a", 1), (1, "#f2b07a", 1)],
        ("#1d1c24", "#35323c", "#433f48"),
        "#1a1520",
        9,
        "#ffd0a0",
        9,
    )
    return doc(b, defs)


ART = {
    "bg-newyear.svg": newyear,
    "bg-snow.svg": snow_scene,
    "bg-moon.svg": moon,
    "bg-sky.svg": sky_scene,
    "bg-farewell.svg": farewell,
    "bg-return.svg": ret,
    "end-shells.svg": end_shells,
    "end-road.svg": end_road,
    "end-sky.svg": end_sky,
}

write_all(ART, sys.argv[1])
