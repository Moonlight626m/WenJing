"""生成《鸿门宴》演出台本的场景背景与结局图（矢量水墨风，1920x1080）。

用法：python3 scripts/demo-art/gen_hongmen.py frontend/public/demo/hongmen
随机元素（星、营帐、火把、碎玉）用固定种子，重跑结果不变。
"""
import math
import random
import sys

from ink import H, W, doc, flying, lin, rad, ridge, write_all

SERIF = "Songti SC, STSong, SimSun, Noto Serif CJK SC, serif"


# ── 器物与人物剪影 ─────────────────────────────────────────────
def ji(x, y, h, angle=0.0, color="#0d0b0a", w=5, tassel="#8c1f17"):
    """一柄戟：长杆，顶上矛尖，侧出一道戈刃，系一绺红缨。(x, y) 是杆脚。"""
    g = f'<g transform="translate({x:.0f} {y:.0f}) rotate({angle:.1f})">'
    g += f'<rect x="{-w / 2:.1f}" y="{-h:.0f}" width="{w}" height="{h:.0f}" fill="{color}"/>'
    g += f'<path d="M{-w:.1f} {-h:.0f} L0 {-h - 46:.0f} L{w:.1f} {-h:.0f} Z" fill="{color}"/>'
    g += f'<path d="M{w / 2:.1f} {-h + 16:.0f} L38 {-h + 4:.0f} L42 {-h + 12:.0f} L{w / 2:.1f} {-h + 30:.0f} Z" fill="{color}"/>'
    if tassel:
        g += f'<path d="M{-w / 2:.1f} {-h + 2:.0f} q -16 12 -9 30 q 4 -14 11 -16 Z" fill="{tassel}"/>'
    return g + "</g>"


def banner(x, y, w, h, glyph="楚", fill="#7a1a14", ink="#e3bd72", sway=0.0):
    """一面竖幡：燕尾下摆，描边，正中一个字。sway 让下摆往一边飘。"""
    s = sway * w
    d = (
        f"M{x} {y} L{x + w} {y} Q{x + w + s * 0.6} {y + h * 0.5} {x + w + s} {y + h} "
        f"L{x + w / 2 + s} {y + h - w * 0.32} L{x + s} {y + h} Q{x + s * 0.6} {y + h * 0.5} {x} {y} Z"
    )
    out = f'<path d="{d}" fill="{fill}"/>'
    out += f'<path d="{d}" fill="#000" opacity="0.18" transform="translate(6 0) scale(1 1)"/>'
    out += f'<rect x="{x + w * 0.1:.0f}" y="{y + w * 0.1:.0f}" width="{w * 0.8:.0f}" height="{h * 0.62:.0f}" fill="none" stroke="{ink}" stroke-width="2" opacity="0.55"/>'
    out += (
        f'<text x="{x + w / 2 + s * 0.2:.0f}" y="{y + h * 0.36:.0f}" font-family="{SERIF}" font-size="{w * 0.6:.0f}" '
        f'font-weight="700" fill="{ink}" text-anchor="middle" dominant-baseline="middle">{glyph}</text>'
    )
    out += f'<rect x="{x - 8}" y="{y - 10}" width="{w + 16}" height="12" rx="4" fill="#2a1a10"/>'
    return out


def flag(x, y, w, h, fill="#8a1d14", wave=1.0):
    """杆头一面横旗，向右飘。(x, y) 是旗杆顶端。"""
    a = 18 * wave
    d = (
        f"M{x} {y} C{x + w * 0.3} {y - a} {x + w * 0.6} {y + a} {x + w} {y} "
        f"L{x + w} {y + h} C{x + w * 0.6} {y + h + a} {x + w * 0.3} {y + h - a} {x} {y + h} Z"
    )
    return f'<path d="{d}" fill="{fill}"/>'


def lamp(x, y, h=420, s=1.0, glow_id="lampGlow"):
    """青铜豆灯：圈足、细柄、灯盘，盘上一朵火苗。(x, y) 是灯脚。"""
    top = y - h * s
    out = f'<circle cx="{x}" cy="{top - 18 * s:.0f}" r="{260 * s:.0f}" fill="url(#{glow_id})"/>'
    out += f'<path d="M{x - 46 * s:.0f} {y} Q{x} {y - 40 * s:.0f} {x + 46 * s:.0f} {y} Z" fill="#2b1d12"/>'
    out += f'<rect x="{x - 7 * s:.0f}" y="{top:.0f}" width="{14 * s:.0f}" height="{h * s - 20 * s:.0f}" fill="#3a2716"/>'
    out += f'<rect x="{x - 2 * s:.0f}" y="{top:.0f}" width="{4 * s:.0f}" height="{h * s - 20 * s:.0f}" fill="#c99a52" opacity="0.35"/>'
    for t in (0.3, 0.62):
        out += f'<ellipse cx="{x}" cy="{top + h * s * t:.0f}" rx="{14 * s:.0f}" ry="{5 * s:.0f}" fill="#4a3220"/>'
    out += f'<path d="M{x - 40 * s:.0f} {top:.0f} Q{x} {top + 26 * s:.0f} {x + 40 * s:.0f} {top:.0f} Z" fill="#4a3220"/>'
    out += f'<ellipse cx="{x}" cy="{top:.0f}" rx="{40 * s:.0f}" ry="{8 * s:.0f}" fill="#6a4a2a"/>'
    out += f'<path d="M{x} {top - 44 * s:.0f} C{x + 14 * s:.0f} {top - 20 * s:.0f} {x + 12 * s:.0f} {top - 4 * s:.0f} {x} {top - 2 * s:.0f} C{x - 12 * s:.0f} {top - 4 * s:.0f} {x - 14 * s:.0f} {top - 20 * s:.0f} {x} {top - 44 * s:.0f} Z" fill="#ffcf7a"/>'
    out += f'<path d="M{x} {top - 30 * s:.0f} C{x + 6 * s:.0f} {top - 16 * s:.0f} {x + 5 * s:.0f} {top - 6 * s:.0f} {x} {top - 4 * s:.0f} C{x - 5 * s:.0f} {top - 6 * s:.0f} {x - 6 * s:.0f} {top - 16 * s:.0f} {x} {top - 30 * s:.0f} Z" fill="#fff6dc"/>'
    return out


def table(x, y, w, d, s=1.0, top="#2a0e0a", edge="#6e1d14"):
    """一张矮案（透视）：案面是梯形，前沿一道朱漆边，四条短腿。(x, y) 是案面前沿中点。"""
    hw, inset = w / 2, w * 0.08
    out = f'<path d="M{x - hw + inset:.0f} {y - d:.0f} L{x + hw - inset:.0f} {y - d:.0f} L{x + hw:.0f} {y:.0f} L{x - hw:.0f} {y:.0f} Z" fill="{top}"/>'
    out += f'<rect x="{x - hw:.0f}" y="{y:.0f}" width="{w:.0f}" height="{12 * s:.0f}" fill="{edge}"/>'
    for lx in (x - hw + 14 * s, x + hw - 24 * s):
        out += f'<rect x="{lx:.0f}" y="{y + 12 * s:.0f}" width="{10 * s:.0f}" height="{34 * s:.0f}" fill="#1a0806"/>'
    return out


def jue_cup(x, y, s=1.0, color="#5a3a1a", tipped=False):
    """一只青铜爵：三足，前有长流，后有尾。tipped 时倒在案上。"""
    rot = 78 if tipped else 0
    g = f'<g transform="translate({x:.0f} {y:.0f}) rotate({rot}) scale({s:.2f})" fill="{color}">'
    g += '<path d="M-16 -46 L16 -46 L13 -14 L-13 -14 Z"/>'
    g += '<path d="M14 -46 L40 -54 L16 -40 Z"/><path d="M-14 -46 L-30 -52 L-14 -40 Z"/>'
    g += '<path d="M-10 -14 L-16 0 M0 -14 L0 2 M10 -14 L16 0" stroke="' + color + '" stroke-width="3"/>'
    g += '<path d="M-8 -52 L-8 -46 M8 -52 L8 -46" stroke="' + color + '" stroke-width="3"/>'
    g += '<path d="M-12 -40 L12 -40" stroke="#c99a52" stroke-width="1.5" opacity="0.5"/>'
    return g + "</g>"


def jue_ring(x, y, r, width, fill="url(#jade)", gap=26, rot=0):
    """玉玦：留一道缺口的玉环。"""
    a0, a1 = math.radians(gap / 2 + rot), math.radians(360 - gap / 2 + rot)
    ro, ri = r, r - width
    p = lambda rr, a: (rr * math.cos(a), rr * math.sin(a))  # noqa: E731
    (x0, y0), (x1, y1) = p(ro, a0), p(ro, a1)
    (x2, y2), (x3, y3) = p(ri, a1), p(ri, a0)
    d = (
        f"M{x + x0:.1f} {y + y0:.1f} A{ro} {ro} 0 1 1 {x + x1:.1f} {y + y1:.1f} "
        f"L{x + x2:.1f} {y + y2:.1f} A{ri} {ri} 0 1 0 {x + x3:.1f} {y + y3:.1f} Z"
    )
    return f'<path d="{d}" fill="{fill}"/>'


def bi_disc(x, y, r, fill="url(#jadeWhite)", s=1.0):
    """白璧：中间有孔的玉璧，面上一圈谷纹。"""
    out = f'<ellipse cx="{x}" cy="{y + r * 0.08:.0f}" rx="{r * 1.05:.0f}" ry="{r * 0.36:.0f}" fill="#000" opacity="0.35"/>'
    out += f'<ellipse cx="{x}" cy="{y}" rx="{r}" ry="{r * 0.34:.0f}" fill="{fill}"/>'
    out += f'<ellipse cx="{x}" cy="{y}" rx="{r * 0.32:.0f}" ry="{r * 0.11:.0f}" fill="#0c0a08" opacity="0.85"/>'
    rng = random.Random(int(x * 7 + y))
    for _ in range(int(40 * s)):
        a = rng.uniform(0, math.tau)
        rr = rng.uniform(0.45, 0.9)
        out += f'<circle cx="{x + r * rr * math.cos(a):.1f}" cy="{y + r * 0.34 * rr * math.sin(a):.1f}" r="{1.6 * s:.1f}" fill="#9fae9a" opacity="0.6"/>'
    out += f'<ellipse cx="{x - r * 0.3:.0f}" cy="{y - r * 0.12:.0f}" rx="{r * 0.4:.0f}" ry="{r * 0.08:.0f}" fill="#fff" opacity="0.35"/>'
    return out


def shard(rng, x, y, size, fill="url(#jade)"):
    """一片碎玉：不规则的五六边形，带一道高光。"""
    n = rng.randint(4, 6)
    pts = []
    for i in range(n):
        a = math.tau * i / n + rng.uniform(-0.3, 0.3)
        rr = size * rng.uniform(0.55, 1.0)
        pts.append((x + rr * math.cos(a), y + rr * 0.6 * math.sin(a)))
    d = "M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in pts) + " Z"
    out = f'<path d="{d}" fill="#000" opacity="0.35" transform="translate(3 4)"/>'
    out += f'<path d="{d}" fill="{fill}"/>'
    (ax, ay), (bx, by) = pts[0], pts[1]
    out += f'<path d="M{ax:.1f} {ay:.1f} L{bx:.1f} {by:.1f}" stroke="#f4fff0" stroke-width="1.6" opacity="0.7"/>'
    return out


def tent(x, y, w, h, fill="#0c1220", door=None, flag_fill=None):
    """一顶营帐（外景）：方底尖顶，门帘透出灯光。(x, y) 是帐底中点。"""
    out = f'<path d="M{x - w / 2:.0f} {y:.0f} L{x - w / 2:.0f} {y - h * 0.5:.0f} L{x:.0f} {y - h:.0f} L{x + w / 2:.0f} {y - h * 0.5:.0f} L{x + w / 2:.0f} {y:.0f} Z" fill="{fill}"/>'
    out += f'<path d="M{x:.0f} {y - h:.0f} L{x + w / 2:.0f} {y - h * 0.5:.0f} L{x + w / 2:.0f} {y:.0f} L{x:.0f} {y:.0f} Z" fill="#000" opacity="0.25"/>'
    if door:
        out += f'<circle cx="{x:.0f}" cy="{y - h * 0.18:.0f}" r="{w * 0.7:.0f}" fill="url(#doorGlow)"/>'
        out += f'<path d="M{x - w * 0.12:.0f} {y:.0f} L{x:.0f} {y - h * 0.4:.0f} L{x + w * 0.12:.0f} {y:.0f} Z" fill="{door}"/>'
    out += f'<path d="M{x:.0f} {y - h:.0f} L{x:.0f} {y - h - h * 0.3:.0f}" stroke="{fill}" stroke-width="{max(1.5, w * 0.03):.1f}"/>'
    if flag_fill:
        out += flag(x, y - h - h * 0.3, w * 0.28, h * 0.12, flag_fill, 0.4)
    return out


def rider(x, y, s=1.0, color="#05070c", flip=False):
    """一人一马的剪影，面朝右（flip 时朝左）。(x, y) 是马蹄落地处。"""
    sx = -s if flip else s
    g = f'<g transform="translate({x:.0f} {y:.0f}) scale({sx:.2f} {s:.2f})" fill="{color}" stroke="{color}" stroke-linecap="round">'
    g += '<ellipse cx="0" cy="-62" rx="54" ry="22" stroke="none"/>'
    g += '<path d="M30 -74 L58 -114 L86 -106 L92 -96 L66 -92 L50 -60 Z" stroke="none"/>'
    g += '<path d="M60 -114 L63 -128 L69 -112 Z" stroke="none"/>'
    g += '<path d="M-36 -50 L-50 -24 L-44 -2 M-24 -46 L-16 -2 M28 -48 L44 -26 L52 -4 M40 -50 L36 -4" stroke-width="7" fill="none"/>'
    g += '<path d="M-52 -70 Q -80 -62 -86 -30" stroke-width="9" fill="none"/>'
    g += '<path d="M-12 -80 L10 -80 L16 -124 L-6 -126 Z" stroke="none"/>'
    g += '<circle cx="5" cy="-138" r="11" stroke="none"/>'
    g += '<path d="M-4 -124 Q -46 -116 -62 -86 L -12 -92 Z" stroke="none" opacity="0.9"/>'
    g += '<path d="M2 -84 L14 -56" stroke-width="7" fill="none"/>'
    return g + "</g>"


def soldier(x, y, s=1.0, color="#0d0909", ji_angle=0.0, ji_side=1):
    """持戟的卫士：披甲、戴胄，戟握在一侧。(x, y) 是脚底。"""
    g = f'<g transform="translate({x:.0f} {y:.0f}) scale({s:.2f})">'
    g += f'<path d="M-26 0 L-20 -70 L20 -70 L26 0 Z" fill="{color}"/>'
    g += f'<path d="M-30 -66 L30 -66 L24 -140 L-24 -140 Z" fill="{color}"/>'
    g += f'<path d="M-34 -136 L34 -136 L28 -118 L-28 -118 Z" fill="{color}"/>'
    g += f'<circle cx="0" cy="-158" r="17" fill="{color}"/>'
    g += f'<path d="M-20 -164 Q0 -196 20 -164 Z" fill="{color}"/><path d="M0 -190 L0 -206" stroke="{color}" stroke-width="4"/>'
    g += '<path d="M0 -206 q 10 -6 4 -16" stroke="#8c1f17" stroke-width="5" fill="none"/>'
    g += ji(ji_side * 34, 0, 300, ji_angle, color, 6)
    return g + "</g>"


def fabric_folds(x0, y0, x1, y1, pitch, grad_id, rng, sag=0):
    """一面帐壁：竖向褶子，每一褶用同一张横向渐变，宽窄略有起伏。"""
    out = ""
    x = x0
    while x < x1:
        w = pitch * rng.uniform(0.75, 1.3)
        out += f'<rect x="{x:.0f}" y="{y0 + rng.uniform(0, sag):.0f}" width="{w + 1:.0f}" height="{y1 - y0:.0f}" fill="url(#{grad_id})"/>'
        x += w
    return out


def valance(y, depth, span, fill, trim=None):
    """帐顶垂下的一圈帷幔，一段一段往下兜。"""
    d = f"M-20 -20 L{W + 20} -20 L{W + 20} {y} "
    x = W + 20
    while x > -20:
        nx = x - span
        d += f"Q{(x + nx) / 2:.0f} {y + depth:.0f} {nx:.0f} {y:.0f} "
        x = nx
    d += "Z"
    out = f'<path d="{d}" fill="{fill}"/>'
    if trim:
        x = W + 20
        t = f"M{x} {y} "
        while x > -20:
            nx = x - span
            t += f"Q{(x + nx) / 2:.0f} {y + depth:.0f} {nx:.0f} {y:.0f} "
            x = nx
        out += f'<path d="{t}" stroke="{trim}" stroke-width="4" fill="none" opacity="0.8"/>'
        for i in range(int((W + 40) / span) + 1):
            tx = W + 20 - span / 2 - i * span
            out += f'<path d="M{tx:.0f} {y + depth / 2:.0f} l 0 {depth * 0.9:.0f}" stroke="{trim}" stroke-width="3" opacity="0.7"/>'
            out += f'<circle cx="{tx:.0f}" cy="{y + depth / 2 + depth * 0.9:.0f}" r="5" fill="{trim}" opacity="0.8"/>'
    return out


def embers(rng, n, x0, x1, y0, y1, color="#ffb35c"):
    out = ""
    for _ in range(n):
        out += f'<circle cx="{rng.uniform(x0, x1):.0f}" cy="{rng.uniform(y0, y1):.0f}" r="{rng.uniform(1, 2.6):.1f}" fill="{color}" opacity="{rng.uniform(0.25, 0.8):.2f}"/>'
    return out


JADE = lin("jade", [(0, "#e2f0d8", 1), (0.5, "#a9c9a6", 1), (1, "#6f9a80", 1)], x2=1, y2=1)
JADE_WHITE = lin("jadeWhite", [(0, "#f4f2e6", 1), (0.6, "#d9dcc8", 1), (1, "#a9b19c", 1)], x2=1, y2=1)


# ── 1 军帐夜怒：深夜的中军大帐，一盏豆灯，案上摊着帛图，酒爵翻倒 ────────────────
def tent_night():
    rng = random.Random(11)
    defs = (
        lin("base", [(0, "#140907", 1), (1, "#24110c", 1)])
        + lin("fold", [(0, "#1c0c08", 1), (0.45, "#4a2116", 1), (0.6, "#52261a", 1), (1, "#1c0c08", 1)], x2=1, y2=0)
        + rad("lampGlow", [(0, "#ffb35c", 0.55), (0.35, "#ff8a3c", 0.18), (1, "#ff8a3c", 0)])
        + rad("warm", [(0, "#ff9a4a", 0.35), (1, "#ff9a4a", 0)])
        + lin("pole", [(0, "#1a0e08", 1), (0.5, "#5a3a22", 1), (1, "#1a0e08", 1)], x2=1, y2=0)
        + lin("floor", [(0, "#2a140c", 1), (1, "#0c0504", 1)])
        + lin("silk", [(0, "#e8d6b0", 1), (1, "#c2a878", 1)], x2=1, y2=1)
        + rad("vig", [(0.55, "#000", 0), (1, "#000", 0.75)], r=0.75)
    )
    b = f'<rect width="{W}" height="{H}" fill="url(#base)"/>'
    b += fabric_folds(-20, 90, W + 20, 860, 96, "fold", rng, sag=20)
    b += '<ellipse cx="1180" cy="520" rx="900" ry="520" fill="url(#warm)"/>'
    b += valance(70, 60, 240, "#0e0605", "#8a5a2a")
    # 帐杆
    for x in (260, 1660):
        b += f'<rect x="{x}" y="40" width="26" height="880" fill="url(#pole)"/>'
        b += f'<rect x="{x - 8}" y="40" width="42" height="14" fill="#2a1a0e"/>'
    # 正中的大幡
    b += banner(860, 170, 200, 430, "楚", "#7e1b13", "#e3bd72")
    for x in (640, 1180):
        b += banner(x, 210, 100, 280, "", "#4a1410", "#c9a35a")
    # 左边兵器架：四柄戟、一张弓
    b += '<rect x="380" y="430" width="16" height="420" fill="#2a1a0e"/><rect x="600" y="430" width="16" height="420" fill="#2a1a0e"/>'
    b += '<rect x="370" y="470" width="256" height="12" fill="#3a2414"/><rect x="370" y="760" width="256" height="12" fill="#3a2414"/>'
    for i, ang in enumerate((-4, -1, 2, 5)):
        b += ji(420 + i * 52, 860, 470, ang, "#120a07", 6)
    b += '<path d="M660 470 Q 720 640 660 810" stroke="#2a1a0e" stroke-width="9" fill="none"/><path d="M660 470 L660 810" stroke="#8a6a44" stroke-width="1.5"/>'
    # 地面与席
    b += f'<rect y="860" width="{W}" height="{H - 860}" fill="url(#floor)"/>'
    b += '<path d="M380 880 L1540 880 L1700 1080 L220 1080 Z" fill="#3a2414" opacity="0.55"/>'
    b += '<path d="M380 880 L1540 880 L1700 1080 L220 1080 Z" fill="none" stroke="#6e4a26" stroke-width="5" opacity="0.6"/>'
    # 帅案：帛图、竹简、翻倒的酒爵
    b += table(960, 820, 980, 70, 1.6, "#1e0b07", "#7a2116")
    b += '<g transform="translate(900 790) rotate(-3)">'
    b += '<path d="M-230 -38 L230 -40 L250 22 L-250 24 Z" fill="url(#silk)"/>'
    b += '<path d="M-200 -10 C -120 -30 -60 10 0 -6 S 120 -30 210 -4" stroke="#3a4a5a" stroke-width="3" fill="none" opacity="0.7"/>'
    b += '<path d="M-150 14 C -90 0 -40 18 30 6" stroke="#3a4a5a" stroke-width="2" fill="none" opacity="0.5"/>'
    b += '<path d="M-60 -32 l 20 -6 l 18 8 l 24 -8 l 20 6" stroke="#5a4a3a" stroke-width="2" fill="none" opacity="0.6"/>'
    b += '<circle cx="-140" cy="-6" r="9" fill="#a32b20"/><circle cx="150" cy="-12" r="9" fill="#2a2a2a"/>'
    b += '<path d="M-131 -6 Q 0 -60 141 -12" stroke="#a32b20" stroke-width="2" stroke-dasharray="6 6" fill="none"/>'
    b += "</g>"
    for i in range(9):
        b += f'<rect x="{1180 + i * 9}" y="736" width="7" height="58" fill="#b49a62" transform="rotate(-8 1220 770)"/>'
    b += '<path d="M1170 750 L1270 736" stroke="#5a3a1a" stroke-width="3" transform="rotate(-8 1220 770)"/>'
    b += jue_cup(620, 800, 1.3, "#5a3a1a", tipped=True)
    b += '<ellipse cx="580" cy="808" rx="70" ry="10" fill="#5a0f0a" opacity="0.8"/>'
    # 豆灯
    b += lamp(1460, 900, 470, 1.15)
    b += embers(rng, 28, 1360, 1560, 260, 520)
    b += f'<rect width="{W}" height="{H}" fill="url(#vig)"/>'
    return doc(b, defs)


# ── 2 项伯夜归：月下连营，篝火点点，一骑从小路回营 ──────────────────────
def camp_night():
    rng = random.Random(12)
    defs = (
        lin("sky", [(0, "#04070f", 1), (0.6, "#0e1a30", 1), (1, "#1c2c48", 1)])
        + rad("moonGlow", [(0, "#e9e2c4", 0.5), (0.3, "#c9c4a8", 0.12), (1, "#c9c4a8", 0)])
        + lin("ground", [(0, "#0b1220", 1), (1, "#03050a", 1)])
        + rad("doorGlow", [(0, "#ffb35c", 0.45), (1, "#ffb35c", 0)])
        + rad("fireGlow", [(0, "#ff9a3c", 0.6), (0.4, "#ff7a2c", 0.15), (1, "#ff7a2c", 0)])
        + lin("path", [(0, "#3a4458", 0.05), (1, "#4a5468", 0.32)])
    )
    b = f'<rect width="{W}" height="{H}" fill="url(#sky)"/>'
    for _ in range(110):
        b += f'<circle cx="{rng.uniform(0, W):.0f}" cy="{rng.uniform(0, 520):.0f}" r="{rng.uniform(0.6, 1.8):.1f}" fill="#dfe8ff" opacity="{rng.uniform(0.15, 0.7):.2f}"/>'
    b += '<circle cx="1480" cy="210" r="300" fill="url(#moonGlow)"/><circle cx="1480" cy="210" r="58" fill="#ece5c8"/>'
    for cx, cy, rx in ((1420, 236, 200), (1180, 290, 260)):
        b += f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="34" fill="#0e1830" opacity="0.55" filter="url(#blur40)"/>'
    b += f'<path d="{ridge(rng, 520, 70, 260)}" fill="#0d1628" filter="url(#ink)"/>'
    b += f'<path d="{ridge(rng, 600, 30, 200)}" fill="#0a111f"/>'
    b += f'<rect y="630" width="{W}" height="{H - 630}" fill="url(#ground)"/>'
    b += '<path d="M1300 1080 L1760 1080 C 1500 900 1260 760 1172 640 L1148 640 C 1200 760 1320 900 1300 1080 Z" fill="url(#path)"/>'
    # 连营：一排一排往近处排，越近越大；给小路留出一条道。帐顶迎着月光的一面勾一道亮边
    for y, s, step in ((646, 0.28, 70), (668, 0.4, 100), (706, 0.58, 150), (770, 0.84, 220), (880, 1.25, 330)):
        x = rng.uniform(-step, 0)
        while x < W + step:
            center = 1160 + (y - 640) * 1.3
            if abs(x - center) > 130 * s + 60:
                lit = rng.random() < 0.38
                b += tent(x, y, 120 * s, 100 * s, "#16203a", "#ffb35c" if lit else None, "#7a1a14" if rng.random() < 0.25 else None)
                w, h = 120 * s, 100 * s
                b += f'<path d="M{x:.0f} {y - h:.0f} L{x + w / 2:.0f} {y - h * 0.5:.0f} L{x + w / 2:.0f} {y:.0f}" stroke="#9fb0d0" stroke-width="{max(1, 2.4 * s):.1f}" fill="none" opacity="0.35"/>'
                if rng.random() < 0.18:
                    fx = x + step * 0.5
                    b += f'<circle cx="{fx:.0f}" cy="{y - 8 * s:.0f}" r="{90 * s:.0f}" fill="url(#fireGlow)"/>'
                    b += f'<path d="M{fx - 9 * s:.0f} {y:.0f} Q{fx:.0f} {y - 40 * s:.0f} {fx + 9 * s:.0f} {y:.0f} Z" fill="#ffc46a"/>'
            x += step * rng.uniform(0.85, 1.2)
    b += f'<rect y="610" width="{W}" height="60" fill="#8090b0" opacity="0.08" filter="url(#blur18)"/>'
    # 一骑回营
    b += '<ellipse cx="1480" cy="968" rx="150" ry="14" fill="#000" opacity="0.4"/>'
    b += rider(1500, 960, 1.6, "#030409", flip=True)
    return doc(b, defs)


# ── 3 鸿门谢罪：拂晓的军门，交戟的卫士，远处一队骑兵沿路而来 ──────────────────
def gate_dawn():
    rng = random.Random(13)
    defs = (
        lin("sky", [(0, "#1d2240", 1), (0.45, "#6a4a60", 1), (0.75, "#e08e68", 1), (1, "#f6c98e", 1)])
        + rad("sun", [(0, "#fff0c8", 0.95), (0.25, "#ffd59a", 0.45), (1, "#ffb070", 0)])
        + lin("ground", [(0, "#3a2a2e", 1), (1, "#120c0e", 1)])
        + lin("road", [(0, "#6a5050", 0.3), (1, "#4a3a3a", 0.55)])
        + lin("farRoad", [(0, "#c9a090", 0.25), (1, "#8a6a64", 0.6)])
        + lin("mist", [(0, "#f2c8a8", 0), (0.5, "#f2c8a8", 0.35), (1, "#f2c8a8", 0)])
    )
    b = f'<rect width="{W}" height="{H}" fill="url(#sky)"/>'
    b += '<circle cx="1260" cy="610" r="420" fill="url(#sun)"/>'
    for i in range(5):
        b += flying(1300 + i * 70 + rng.uniform(-20, 20), 260 + rng.uniform(-40, 40), rng.uniform(0.5, 0.8), "#2a1e28", 0.7)
    b += f'<path d="{ridge(rng, 560, 50, 260)}" fill="#7a5468" opacity="0.55" filter="url(#ink)"/>'
    b += f'<path d="{ridge(rng, 620, 30, 220)}" fill="#4a3346"/>'
    b += f'<rect y="650" width="{W}" height="{H - 650}" fill="url(#ground)"/>'
    b += f'<rect y="620" width="{W}" height="110" fill="url(#mist)" filter="url(#blur18)"/>'
    # 门外的路一直通到山脚，一队骑兵沿路而来（从军门里望出去）
    b += '<path d="M900 780 L1020 780 C 1000 740 1080 700 1010 652 L996 652 C 1040 700 950 740 900 780 Z" fill="url(#farRoad)"/>'
    for x, y, s, flip in ((1003, 664, 0.13, True), (1018, 690, 0.17, True), (990, 712, 0.21, False), (968, 742, 0.26, False)):
        b += rider(x, y, s, "#1a1216", flip)
    b += '<path d="M972 742 L972 694" stroke="#1a1216" stroke-width="2"/>' + flag(972, 694, 22, 10, "#1a1216", 0.3)
    # 栅栏
    for x0, x1 in ((-20, 800), (1120, W + 20)):
        x = x0
        while x < x1:
            h = rng.uniform(150, 185)
            b += f'<path d="M{x:.0f} 770 L{x:.0f} {770 - h:.0f} L{x + 13:.0f} {770 - h - 22:.0f} L{x + 26:.0f} {770 - h:.0f} L{x + 26:.0f} 770 Z" fill="#1a1012"/>'
            x += 30
        b += f'<rect x="{x0}" y="660" width="{x1 - x0}" height="9" fill="#120a0c"/><rect x="{x0}" y="728" width="{x1 - x0}" height="9" fill="#120a0c"/>'
    # 军门：两根门柱一道横梁，柱顶大旗
    for x in (800, 1086):
        b += f'<rect x="{x}" y="380" width="34" height="400" fill="#140c0e"/>'
        b += f'<rect x="{x + 13}" y="150" width="8" height="240" fill="#140c0e"/>'
    b += '<path d="M770 400 L1150 400 L1136 430 L784 430 Z" fill="#140c0e"/>'
    b += '<path d="M760 392 L1160 392 L1150 372 L770 372 Z" fill="#1e1214"/>'
    b += flag(821, 160, 170, 92, "#8a1d14", 1.0) + flag(1107, 170, 160, 86, "#7a1a14", 0.8)
    b += f'<text x="900" y="214" font-family="{SERIF}" font-size="56" font-weight="700" fill="#e3bd72" text-anchor="middle" dominant-baseline="middle">楚</text>'
    b += '<path d="M834 780 L1086 780 L1500 1080 L420 1080 Z" fill="url(#road)"/>'
    # 交戟的卫士
    b += soldier(850, 830, 1.15, "#0d0809", 26, 1)
    b += soldier(1070, 830, 1.15, "#0d0809", -26, -1)
    for x, s in ((700, 1.0), (1220, 1.0), (560, 0.9), (1360, 0.9)):
        b += soldier(x, 830 + (1 - s) * 40, s, "#0f0a0b", rng.uniform(-3, 3), 1 if x < 960 else -1)
    return doc(b, defs)


# ── 4 举玦舞剑：大帐里的酒宴，两列矮案，正中一道剑光；前景是亚父举起的玉玦 ──────────
def banquet():
    rng = random.Random(14)
    defs = (
        lin("base", [(0, "#1a0807", 1), (1, "#2a0d0a", 1)])
        + lin("fold", [(0, "#2a0a08", 1), (0.5, "#7a2216", 1), (1, "#2a0a08", 1)], x2=1, y2=0)
        + rad("lampGlow", [(0, "#ffc070", 0.5), (0.35, "#ff9a4a", 0.14), (1, "#ff9a4a", 0)])
        + lin("carpet", [(0, "#5a1610", 1), (1, "#8a2418", 1)])
        + lin("floor", [(0, "#1e0a07", 1), (1, "#0a0403", 1)])
        + lin("screen", [(0, "#1a0a08", 1), (1, "#0e0504", 1)])
        + lin("blade", [(0, "#ffffff", 0), (0.4, "#e8fbff", 0.85), (0.7, "#9fe8ff", 0.9), (1, "#ffffff", 0)], x2=1, y2=0)
        + JADE
        + rad("vig", [(0.5, "#000", 0), (1, "#000", 0.7)], r=0.75)
    )
    b = f'<rect width="{W}" height="{H}" fill="url(#base)"/>'
    b += fabric_folds(-20, 60, W + 20, 640, 120, "fold", rng, sag=10)
    b += valance(60, 70, 300, "#140504", "#c9a35a")
    # 正中屏风：黑漆描金山水
    b += '<rect x="700" y="250" width="520" height="330" fill="url(#screen)"/>'
    b += '<rect x="700" y="250" width="520" height="330" fill="none" stroke="#c9a35a" stroke-width="6"/>'
    for x in (830, 960, 1090):
        b += f'<path d="M{x} 250 L{x} 580" stroke="#c9a35a" stroke-width="3" opacity="0.6"/>'
    b += '<path d="M716 520 C 760 440 800 470 840 420 S 920 380 960 450 S 1060 400 1100 440 S 1180 470 1204 430" stroke="#c9a35a" stroke-width="3" fill="none" opacity="0.65"/>'
    b += '<path d="M716 550 C 800 520 900 540 1000 520 S 1150 540 1204 520" stroke="#c9a35a" stroke-width="2" fill="none" opacity="0.4"/>'
    b += '<circle cx="1120" cy="320" r="26" fill="none" stroke="#c9a35a" stroke-width="3" opacity="0.6"/>'
    # 地面、红毡
    b += f'<rect y="620" width="{W}" height="{H - 620}" fill="url(#floor)"/>'
    b += '<path d="M820 620 L1100 620 L1440 1080 L480 1080 Z" fill="url(#carpet)"/>'
    b += '<path d="M820 620 L480 1080 M1100 620 L1440 1080" stroke="#c9a35a" stroke-width="4" opacity="0.6"/>'
    # 两列矮案，往里越来越小
    for side in (-1, 1):
        for i, (dx, y, s) in enumerate(((560, 1010, 1.25), (380, 820, 0.9), (250, 700, 0.62))):
            x = 960 + side * dx
            b += table(x, y, 360 * s, 70 * s, s)
            b += jue_cup(x - side * 60 * s, y - 24 * s, 0.9 * s, "#6a4a2a")
            b += f'<ellipse cx="{x + side * 40 * s:.0f}" cy="{y - 30 * s:.0f}" rx="{46 * s:.0f}" ry="{12 * s:.0f}" fill="#4a2a18"/>'
            b += f'<ellipse cx="{x + side * 40 * s:.0f}" cy="{y - 34 * s:.0f}" rx="{30 * s:.0f}" ry="{7 * s:.0f}" fill="#8a5a3a"/>'
        for dx, y, s in ((720, 860, 1.0), (440, 680, 0.7)):
            b += lamp(960 + side * dx, y, 380, s)
    # 剑光：一道弧，从左上划到右下
    b += '<path d="M660 520 C 860 420 1180 520 1320 760" stroke="#bff3ff" stroke-width="40" fill="none" opacity="0.25" filter="url(#blur18)"/>'
    b += '<path d="M660 520 C 860 420 1180 520 1320 760" stroke="url(#blade)" stroke-width="9" fill="none"/>'
    b += '<path d="M700 506 C 880 430 1150 520 1290 720" stroke="#ffffff" stroke-width="2" fill="none" opacity="0.8"/>'
    b += '<g transform="translate(1320 760) rotate(58)"><path d="M0 -6 L150 -3 L170 0 L150 3 L0 6 Z" fill="#e8f2f4"/>'
    b += '<rect x="-14" y="-16" width="10" height="32" fill="#8a6a3a"/><rect x="-60" y="-5" width="46" height="10" fill="#3a2414"/></g>'
    b += embers(rng, 40, 300, 1620, 200, 700, "#ffc070")
    # 前景：亚父举起的玉玦，红绳从画外垂下，焦外虚化
    b += '<g filter="url(#blur6)" opacity="0.92">'
    b += '<path d="M236 -20 L236 160" stroke="#8c1f17" stroke-width="7"/>'
    b += jue_ring(236, 270, 112, 44, "url(#jade)", 30, -90)
    b += '<path d="M180 190 A 100 100 0 0 0 150 260" stroke="#ffffff" stroke-width="6" fill="none" opacity="0.5"/>'
    b += "</g>"
    b += f'<rect width="{W}" height="{H}" fill="url(#vig)"/>'
    return doc(b, defs)


# ── 5 樊哙闯帐：帷帐被一把掀开，天光涌进来，门口立着一个拥盾带剑的壮士 ────────────
def fankuai():
    rng = random.Random(15)
    defs = (
        lin("base", [(0, "#140908", 1), (1, "#0a0504", 1)])
        + lin("outside", [(0, "#fff6e2", 1), (0.6, "#f6d6a0", 1), (1, "#d9a86a", 1)])
        + lin("ray", [(0, "#fff1d6", 0.5), (1, "#fff1d6", 0)])
        + lin("curtainL", [(0, "#1a0807", 1), (0.6, "#5a1a12", 1), (1, "#7a2618", 1)], x2=1, y2=0)
        + lin("curtainR", [(0, "#7a2618", 1), (0.4, "#5a1a12", 1), (1, "#1a0807", 1)], x2=1, y2=0)
        + lin("floor", [(0, "#24100a", 1), (1, "#080302", 1)])
        + rad("vig", [(0.45, "#000", 0), (1, "#000", 0.8)], r=0.75)
    )
    # 掀开的帐口：尖拱形，上窄下宽
    left_edge = "C 840 170 740 420 660 920"
    right_edge = "C 1080 170 1180 420 1260 920"
    opening = f"M960 100 {left_edge} L1260 920 C 1180 420 1080 170 960 100 Z"
    b = f'<rect width="{W}" height="{H}" fill="url(#base)"/>'
    # 帐外的天光
    b += f'<path d="{opening}" fill="url(#outside)"/>'
    b += f'<path d="{opening}" fill="#ffffff" opacity="0.35" filter="url(#blur40)"/>'
    b += f'<rect y="900" width="{W}" height="{H - 900}" fill="url(#floor)"/>'
    # 光柱铺到地上
    for x0, x1, xa, xb in ((660, 860, 80, 640), (860, 1060, 640, 1280), (1060, 1260, 1280, 1860)):
        b += f'<path d="M{x0} 920 L{x1} 920 L{xb} 1080 L{xa} 1080 Z" fill="url(#ray)" opacity="0.55"/>'
    for i in range(7):
        a = -60 + i * 20
        b += f'<path d="M960 600 L{960 + 1400 * math.sin(math.radians(a)):.0f} {600 + 1400 * math.cos(math.radians(a)):.0f}" stroke="#fff1d6" stroke-width="{rng.uniform(30, 70):.0f}" opacity="0.06" filter="url(#blur18)"/>'
    # 两扇被掀开的帷帐，褶子往外兜
    b += f'<path d="M-20 -20 L960 -20 L960 100 {left_edge} L-20 920 Z" fill="url(#curtainL)"/>'
    b += f'<path d="M1940 -20 L960 -20 L960 100 {right_edge} L1940 920 Z" fill="url(#curtainR)"/>'
    for i in range(9):
        x = 40 + i * 80
        b += f'<path d="M{x} -20 C {x + 40} 300 {x + 20 + i * 8} 600 {x - 40 + i * 18} 920" stroke="#0e0403" stroke-width="{rng.uniform(6, 14):.0f}" fill="none" opacity="0.5"/>'
        x2 = W - 40 - i * 80
        b += f'<path d="M{x2} -20 C {x2 - 40} 300 {x2 - 20 - i * 8} 600 {x2 + 40 - i * 18} 920" stroke="#0e0403" stroke-width="{rng.uniform(6, 14):.0f}" fill="none" opacity="0.5"/>'
    b += f'<path d="M960 100 {left_edge}" stroke="#ffd9a0" stroke-width="5" fill="none" opacity="0.7"/>'
    b += f'<path d="M960 100 {right_edge}" stroke="#ffd9a0" stroke-width="5" fill="none" opacity="0.7"/>'
    # 仆地的卫士，戟横在地上
    for x, flip in ((600, 1), (1320, -1)):
        b += f'<g transform="translate({x} 1000) scale({flip} 1)" fill="#120807">'
        b += '<rect x="-110" y="-24" width="170" height="44" rx="20"/>'
        b += '<circle cx="84" cy="-6" r="24"/><path d="M66 -24 Q 84 -46 104 -26 Z"/>'
        b += '<path d="M-110 -10 L-200 -2 L-200 20 L-110 14 Z"/>'
        b += '<path d="M40 -20 L60 -70 L76 -66 L60 -16 Z"/>'
        b += "</g>"
    b += ji(260, 1040, 560, 86, "#1a0c09", 6)
    b += ji(1660, 1040, 560, -86, "#1a0c09", 6)
    # 樊哙：西向而立，左臂拥盾，右手带剑，头发上指
    k = "#0a0504"
    b += f'<g transform="translate(960 920)" fill="{k}">'
    b += '<ellipse cx="0" cy="4" rx="190" ry="16" fill="#000" opacity="0.5"/>'
    b += '<path d="M-52 -250 L-8 -250 L-96 0 L-156 0 Z"/><path d="M8 -250 L52 -250 L150 0 L90 0 Z"/>'
    b += '<path d="M-166 -6 L-90 -6 L-86 6 L-170 6 Z"/><path d="M84 -6 L160 -6 L164 6 L80 6 Z"/>'
    b += '<path d="M-70 -306 L70 -306 L114 -196 L86 -208 L57 -192 L28 -208 L0 -192 L-28 -208 L-57 -192 L-86 -208 L-114 -196 Z"/>'
    b += '<path d="M-118 -476 L118 -476 Q 132 -420 92 -300 L-92 -300 Q -132 -420 -118 -476 Z"/>'
    b += '<rect x="-84" y="-318" width="168" height="18" fill="#2a1610"/>'
    b += '<ellipse cx="-118" cy="-466" rx="38" ry="24"/><ellipse cx="118" cy="-466" rx="38" ry="24"/>'
    b += '<rect x="-20" y="-506" width="40" height="36"/>'
    b += '<circle cx="0" cy="-534" r="38"/>'
    b += '<path d="M-30 -516 Q 0 -470 30 -516 L22 -490 Q 0 -462 -22 -490 Z"/>'
    for i in range(13):
        base = -30 + i * 5
        lean = (i - 6) * 6 + rng.uniform(-8, 8)
        length = rng.uniform(64, 118) - abs(i - 6) * 5
        b += f'<path d="M{base - 5:.0f} -556 Q{base + lean * 0.3:.0f} {-556 - length * 0.5:.0f} {base + lean:.0f} {-556 - length:.0f} L{base + 5:.0f} -556 Z"/>'
    b += '<path d="M118 -462 L176 -380 L206 -282" stroke="#0a0504" stroke-width="40" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
    b += '<g transform="translate(206 -276) rotate(-22)">'
    b += '<path d="M-7 10 L-5 270 L0 300 L5 270 L7 10 Z" fill="#dfe6e8"/><path d="M0 10 L0 290" stroke="#ffffff" stroke-width="1.5" opacity="0.7"/>'
    b += '<rect x="-30" y="-2" width="60" height="12" fill="#2a1a10"/><rect x="-6" y="-40" width="12" height="40" fill="#2a1a10"/></g>'
    b += '<path d="M-118 -462 L-176 -400 L-170 -340" stroke="#0a0504" stroke-width="40" stroke-linecap="round" stroke-linejoin="round" fill="none"/>'
    b += '<path d="M-262 -560 Q -216 -590 -170 -560 Q -124 -590 -78 -560 L-84 -264 Q -170 -232 -256 -264 Z"/>'
    b += '<path d="M-170 -556 L-170 -250" stroke="#3a1a10" stroke-width="5"/>'
    b += '<path d="M-250 -540 Q -216 -568 -170 -544 Q -124 -568 -90 -540" stroke="#3a1a10" stroke-width="4" fill="none"/>'
    b += '<circle cx="-170" cy="-410" r="22" fill="#2a1a10"/>'
    b += "</g>"
    b += embers(rng, 70, 720, 1200, 160, 900, "#fff1d6")
    b += f'<rect width="{W}" height="{H}" fill="url(#vig)"/>'
    return doc(b, defs)


# ── 6 宴罢当夜：冷下来的大帐，一支残烛，坐上一双白璧，地上碎了的玉斗和一柄剑 ──────────
def aftermath():
    rng = random.Random(16)
    defs = (
        lin("base", [(0, "#0a0e16", 1), (1, "#141a24", 1)])
        + lin("fold", [(0, "#0c1018", 1), (0.5, "#202838", 1), (1, "#0c1018", 1)], x2=1, y2=0)
        + rad("candle", [(0, "#ffc070", 0.5), (0.3, "#ff9a4a", 0.14), (1, "#ff9a4a", 0)])
        + lin("night", [(0, "#060a14", 1), (1, "#18243c", 1)])
        + lin("floor", [(0, "#161c26", 1), (1, "#06080c", 1)])
        + JADE
        + JADE_WHITE
        + rad("vig", [(0.4, "#000", 0), (1, "#000", 0.75)], r=0.75)
    )
    b = f'<rect width="{W}" height="{H}" fill="url(#base)"/>'
    b += fabric_folds(-20, 80, W + 20, 760, 110, "fold", rng, sag=16)
    b += valance(70, 50, 260, "#06080c", "#4a5262")
    # 掀开一角的帐门：外面是夜
    b += '<path d="M220 120 L470 120 L520 760 L170 760 Z" fill="url(#night)"/>'
    for _ in range(26):
        b += f'<circle cx="{rng.uniform(190, 500):.0f}" cy="{rng.uniform(140, 560):.0f}" r="{rng.uniform(0.6, 1.6):.1f}" fill="#dfe8ff" opacity="{rng.uniform(0.2, 0.8):.2f}"/>'
    b += '<path d="M380 200 a 30 30 0 1 0 22 50 a 24 24 0 1 1 -22 -50 Z" fill="#e8e2c8" opacity="0.8"/>'
    b += '<path d="M470 120 Q 560 400 520 760 L620 760 Q 640 400 560 120 Z" fill="#1a2030"/>'
    b += '<path d="M220 120 Q 150 400 170 760 L120 760 Q 100 400 150 120 Z" fill="#1a2030"/>'
    b += banner(1320, 170, 150, 330, "楚", "#3a1412", "#8a7a5a")
    b += f'<rect y="760" width="{W}" height="{H - 760}" fill="url(#floor)"/>'
    # 矮案、残烛
    b += table(1240, 800, 560, 64, 1.3, "#10141c", "#3a1a16")
    b += '<circle cx="1380" cy="700" r="380" fill="url(#candle)"/>'
    b += '<rect x="1368" y="700" width="24" height="70" fill="#d8cfb4"/><path d="M1368 704 q 6 18 0 30" stroke="#b8ad90" stroke-width="5" fill="none"/>'
    b += '<path d="M1380 662 C1392 682 1390 694 1380 698 C1370 694 1368 682 1380 662 Z" fill="#ffd27a"/>'
    b += '<ellipse cx="1380" cy="770" rx="34" ry="6" fill="#3a2a1a"/>'
    b += jue_cup(1150, 770, 1.0, "#3a3020")
    # 坐席上的一双白璧
    b += '<path d="M640 830 L940 830 L980 900 L600 900 Z" fill="#2a1a20"/><path d="M640 830 L940 830 L980 900 L600 900 Z" fill="none" stroke="#6a3a3a" stroke-width="4"/>'
    b += bi_disc(730, 850, 70) + bi_disc(860, 862, 64)
    # 地上碎了的玉斗，旁边一柄剑
    for _ in range(26):
        x = rng.gauss(980, 140)
        y = rng.gauss(990, 30)
        b += shard(rng, x, y, rng.uniform(10, 30))
    b += '<g transform="translate(1260 1000) rotate(-14)"><path d="M-300 -5 L40 -4 L64 0 L40 4 L-300 5 Z" fill="#9aa4ac"/>'
    b += '<path d="M-300 -1 L40 0" stroke="#e8f0f4" stroke-width="1.5" opacity="0.7"/>'
    b += '<rect x="-320" y="-16" width="14" height="32" fill="#5a4a2a"/><rect x="-380" y="-6" width="60" height="12" fill="#2a1a10"/></g>'
    b += f'<rect width="{W}" height="{H}" fill="url(#vig)"/>'
    return doc(b, defs)


# ── 结局 · 拾玉：一方青绸上，碎玉拼回一只玉斗，裂纹还在 ────────────────────────
def end_jade():
    rng = random.Random(21)
    defs = (
        lin("wood", [(0, "#24160e", 1), (1, "#0e0805", 1)])
        + lin("cloth", [(0, "#5a1612", 1), (0.5, "#3a0c0a", 1), (1, "#240706", 1)], x2=1, y2=1)
        + rad("candle", [(0, "#ffc070", 0.5), (0.4, "#ff9a4a", 0.12), (1, "#ff9a4a", 0)])
        + lin("cupBody", [(0, "#d8ead2", 1), (0.45, "#a2c4a0", 1), (1, "#5a8068", 1)], x2=1, y2=0)
        + lin("cupInner", [(0, "#4a705a", 1), (1, "#8ab496", 1)])
        + JADE
        + JADE_WHITE
        + rad("vig", [(0.45, "#000", 0), (1, "#000", 0.72)], r=0.75)
    )
    b = f'<rect width="{W}" height="{H}" fill="url(#wood)"/>'
    for i in range(16):
        y = i * 72 + rng.uniform(-8, 8)
        b += f'<path d="M0 {y:.0f} Q 960 {y + rng.uniform(-24, 24):.0f} 1920 {y:.0f}" stroke="#000" stroke-width="2" opacity="0.25" fill="none"/>'
    # 一方朱绸，边角随手一摊
    b += '<path d="M360 300 C 620 220 900 280 1180 230 S 1560 260 1640 330 C 1600 520 1680 720 1580 900 C 1300 960 980 900 700 950 S 380 900 330 820 C 380 640 300 480 360 300 Z" fill="url(#cloth)" filter="url(#inkSoft)"/>'
    for x0 in (520, 760, 1040, 1320):
        b += f'<path d="M{x0} 260 C {x0 + 60} 480 {x0 - 40} 700 {x0 + 30} 930" stroke="#1a0404" stroke-width="16" fill="none" opacity="0.35" filter="url(#blur6)"/>'
        b += f'<path d="M{x0 + 18} 260 C {x0 + 78} 480 {x0 - 22} 700 {x0 + 48} 930" stroke="#8a2a20" stroke-width="5" fill="none" opacity="0.25" filter="url(#blur6)"/>'
    b += '<circle cx="360" cy="180" r="820" fill="url(#candle)"/>'
    # 玉斗：侧上方看下去，斗口一圈椭圆，斗身往下收，一侧伸出短柄；裂纹拼回去还在
    cx, cy = 900, 520
    b += f'<ellipse cx="{cx + 20}" cy="{cy + 250}" rx="260" ry="40" fill="#000" opacity="0.4" filter="url(#blur6)"/>'
    b += f'<path d="M{cx - 230} {cy} C {cx - 226} {cy + 160} {cx - 140} {cy + 250} {cx} {cy + 252} C {cx + 140} {cy + 250} {cx + 226} {cy + 160} {cx + 230} {cy} Z" fill="url(#cupBody)"/>'
    b += f'<ellipse cx="{cx}" cy="{cy}" rx="230" ry="62" fill="url(#cupInner)"/>'
    b += f'<ellipse cx="{cx}" cy="{cy}" rx="230" ry="62" fill="none" stroke="#eef8ea" stroke-width="5"/>'
    b += f'<ellipse cx="{cx}" cy="{cy + 6}" rx="200" ry="48" fill="#2e4a3c" opacity="0.45"/>'
    b += f'<path d="M{cx + 222} {cy + 40} C {cx + 300} {cy + 20} {cx + 380} {cy + 30} {cx + 430} {cy + 70} L{cx + 416} {cy + 104} C {cx + 360} {cy + 74} {cx + 300} {cy + 80} {cx + 214} {cy + 104} Z" fill="url(#cupBody)"/>'
    b += f'<path d="M{cx - 180} {cy + 60} C {cx - 170} {cy + 150} {cx - 120} {cy + 210} {cx - 60} {cy + 232}" stroke="#ffffff" stroke-width="10" fill="none" opacity="0.35"/>'
    for d in (
        f"M{cx - 150} {cy + 40} L{cx - 110} {cy + 110} L{cx - 140} {cy + 170} L{cx - 90} {cy + 226}",
        f"M{cx - 20} {cy + 60} L{cx + 20} {cy + 130} L{cx - 10} {cy + 190} L{cx + 30} {cy + 250}",
        f"M{cx + 140} {cy + 50} L{cx + 100} {cy + 120} L{cx + 160} {cy + 170}",
        f"M{cx - 110} {cy + 110} L{cx + 20} {cy + 130}",
        f"M{cx - 10} {cy + 190} L{cx + 160} {cy + 170}",
        f"M{cx + 300} {cy + 36} L{cx + 316} {cy + 84}",
        f"M{cx - 60} {cy - 56} L{cx - 40} {cy - 20} L{cx - 70} {cy + 20}",
    ):
        b += f'<path d="{d}" stroke="#1d2a24" stroke-width="5" fill="none" stroke-linejoin="round"/>'
        b += f'<path d="{d}" stroke="#f4fff0" stroke-width="1.5" fill="none" opacity="0.55" transform="translate(3 -2)"/>'
    # 斗口缺了一块，缺下来的那片还在绸上
    b += f'<path d="M{cx + 120} {cy - 54} L{cx + 190} {cy - 34} L{cx + 172} {cy - 8} L{cx + 110} {cy - 20} Z" fill="#2a0a08"/>'
    b += shard(rng, 1330, 820, 34)
    for x, y, sz in ((560, 840, 22), (640, 880, 14), (1240, 860, 16), (1460, 760, 12), (500, 420, 14)):
        b += shard(rng, x, y, sz)
    b += bi_disc(1680, 980, 150, s=1.6)
    b += f'<rect width="{W}" height="{H}" fill="url(#vig)"/>'
    return doc(b, defs)


# ── 结局 · 霸上烽火：夜里的霸水，烽火台举火，一列列火把连夜拔营 ─────────────────
def end_beacon():
    rng = random.Random(22)
    defs = (
        lin("sky", [(0, "#05070f", 1), (0.55, "#1a1428", 1), (0.85, "#5a2418", 1), (1, "#8a3a1a", 1)])
        + rad("fireGlow", [(0, "#ffb050", 0.75), (0.3, "#ff7a2c", 0.25), (1, "#ff7a2c", 0)])
        + rad("torch", [(0, "#ffc46a", 0.9), (1, "#ff7a2c", 0)])
        + lin("land", [(0, "#120c10", 1), (1, "#040305", 1)])
        + lin("river", [(0, "#3a2420", 1), (1, "#120c12", 1)])
    )
    b = f'<rect width="{W}" height="{H}" fill="url(#sky)"/>'
    for _ in range(70):
        b += f'<circle cx="{rng.uniform(0, W):.0f}" cy="{rng.uniform(0, 380):.0f}" r="{rng.uniform(0.6, 1.6):.1f}" fill="#dfe8ff" opacity="{rng.uniform(0.15, 0.6):.2f}"/>'
    # 烽烟
    for i in range(14):
        cx = 1460 + i * 26 + rng.uniform(-30, 30)
        cy = 480 - i * 34
        b += f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{70 + i * 14:.0f}" ry="{40 + i * 6:.0f}" fill="#3a2424" opacity="{0.55 - i * 0.03:.2f}" filter="url(#blur18)"/>'
    b += f'<path d="{ridge(rng, 560, 60, 280)}" fill="#160e14" filter="url(#ink)"/>'
    # 烽火台
    b += '<circle cx="1440" cy="500" r="320" fill="url(#fireGlow)"/>'
    b += '<path d="M1380 620 L1500 620 L1484 520 L1396 520 Z" fill="#0c080a"/>'
    b += '<path d="M1388 520 L1492 520 L1492 508 L1388 508 Z" fill="#0c080a"/>'
    for i in range(5):
        b += f'<path d="M{1404 + i * 18} 508 Q {1412 + i * 18} {440 - rng.uniform(0, 40):.0f} {1424 + i * 18} 508 Z" fill="#ffb050"/>'
    b += '<path d="M1416 508 Q 1440 420 1464 508 Z" fill="#fff0c0"/>'
    b += f'<path d="{ridge(rng, 650, 30, 220)}" fill="url(#land)"/>'
    # 霸水
    b += '<path d="M-20 900 C 300 860 520 760 760 740 S 1160 700 1300 690 L 1300 702 C 1160 716 960 744 780 770 S 340 900 -20 960 Z" fill="url(#river)"/>'
    for _ in range(40):
        t = rng.uniform(0, 1)
        x = -20 + t * 1300
        y = 920 - t * 220 + rng.uniform(-10, 10)
        b += f'<rect x="{x:.0f}" y="{y:.0f}" width="{rng.uniform(20, 60) * (1 - t * 0.7):.0f}" height="2" fill="#ffb050" opacity="{rng.uniform(0.2, 0.6):.2f}"/>'
    # 一列列火把，沿路向山口
    for k in range(4):
        x0, y0 = 300 + k * 160, 1000 - k * 30
        x1, y1 = 1120 + k * 40, 660 + k * 6
        cx, cy = 700 + k * 120, 860 - k * 40
        for i in range(34):
            t = i / 33
            x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1 + rng.uniform(-6, 6)
            y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1 + rng.uniform(-4, 4)
            r = 3.4 * (1 - t * 0.7)
            b += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r * 4:.1f}" fill="url(#torch)" opacity="0.5"/>'
            b += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.1f}" fill="#ffd27a"/>'
    # 前景：楚营望台的一角，大旗与戟
    b += '<path d="M-20 1080 L-20 880 Q 200 860 360 900 L420 1080 Z" fill="#050305"/>'
    b += '<rect x="120" y="360" width="12" height="560" fill="#050305"/>' + flag(132, 370, 210, 110, "#5a1410", 1.2)
    b += f'<text x="230" y="428" font-family="{SERIF}" font-size="60" font-weight="700" fill="#c9a35a" text-anchor="middle" dominant-baseline="middle" opacity="0.85">楚</text>'
    for i in range(3):
        b += ji(220 + i * 40, 1000, 380, -8 + i * 6, "#050305", 5, None)
    return doc(b, defs)


# ── 结局 · 鸿门一诺：月下的楚营，矮案上两只酒爵相对，一卷书信系着红绳 ───────────
def end_promise():
    rng = random.Random(23)
    defs = (
        lin("sky", [(0, "#070c1c", 1), (0.6, "#1a2848", 1), (1, "#3a4a6e", 1)])
        + rad("moonGlow", [(0, "#ffe9b8", 0.6), (0.3, "#f2d8a0", 0.16), (1, "#f2d8a0", 0)])
        + rad("moonFace", [(0, "#fff6d8", 1), (0.8, "#f2dca0", 1), (1, "#d9b878", 1)], cx=0.42, cy=0.4)
        + lin("land", [(0, "#10162a", 1), (1, "#05070e", 1)])
        + rad("doorGlow", [(0, "#ffb35c", 0.35), (1, "#ffb35c", 0)])
        + lin("tableTop", [(0, "#2a1a14", 1), (1, "#4a2c1e", 1)])
        + lin("slip", [(0, "#d9c38a", 1), (1, "#a88a52", 1)], x2=1, y2=0)
    )
    b = f'<rect width="{W}" height="{H}" fill="url(#sky)"/>'
    for _ in range(80):
        b += f'<circle cx="{rng.uniform(0, W):.0f}" cy="{rng.uniform(0, 460):.0f}" r="{rng.uniform(0.6, 1.6):.1f}" fill="#eef2ff" opacity="{rng.uniform(0.2, 0.7):.2f}"/>'
    b += '<circle cx="1360" cy="290" r="440" fill="url(#moonGlow)"/><circle cx="1360" cy="290" r="128" fill="url(#moonFace)"/>'
    for cx, cy, r in ((1320, 250, 20), (1410, 330, 14), (1390, 230, 10)):
        b += f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="#d9b878" opacity="0.3"/>'
    b += f'<path d="{ridge(rng, 600, 50, 280)}" fill="#141c34" filter="url(#ink)"/>'
    b += f'<rect y="660" width="{W}" height="{H - 660}" fill="url(#land)"/>'
    for x, s in ((260, 0.7), (420, 0.5), (1600, 0.75), (1760, 0.55), (1480, 0.45)):
        b += tent(x, 690, 160 * s, 130 * s, "#0a0f1e", "#ffb35c" if s > 0.6 else None, "#5a1410")
    # 矮案：两只爵相对，一卷书信
    b += '<path d="M560 840 L1360 840 L1480 980 L440 980 Z" fill="url(#tableTop)"/>'
    b += '<path d="M560 840 L1360 840" stroke="#f2dca0" stroke-width="3" opacity="0.5"/>'
    b += '<rect x="440" y="980" width="1040" height="22" fill="#5a1a14"/>'
    for lx in (480, 1420):
        b += f'<rect x="{lx}" y="1002" width="22" height="78" fill="#0c0606"/>'
    b += jue_cup(800, 930, 2.0, "#7a5a2a")
    b += '<g transform="translate(1120 930) scale(-1 1)">' + jue_cup(0, 0, 2.0, "#7a5a2a") + "</g>"
    b += '<path d="M770 830 L790 840 M1150 830 L1130 840" stroke="#f2dca0" stroke-width="3" opacity="0.6"/>'
    b += '<g transform="translate(960 940) rotate(-6)">'
    b += '<rect x="-90" y="-26" width="180" height="52" rx="24" fill="url(#slip)"/>'
    for i in range(9):
        b += f'<path d="M{-80 + i * 20} -24 L{-80 + i * 20} 24" stroke="#7a5a2a" stroke-width="2" opacity="0.6"/>'
    b += '<rect x="-10" y="-30" width="20" height="60" fill="#a32b20"/><path d="M0 30 q -10 30 -26 40 M0 30 q 10 30 22 44" stroke="#a32b20" stroke-width="5" fill="none"/>'
    b += "</g>"
    for _ in range(30):
        b += f'<circle cx="{rng.uniform(200, 1700):.0f}" cy="{rng.uniform(600, 840):.0f}" r="{rng.uniform(1, 2.4):.1f}" fill="#ffe9a8" opacity="{rng.uniform(0.3, 0.8):.2f}"/>'
    return doc(b, defs)


ART = {
    "bg-tent.svg": tent_night,
    "bg-camp.svg": camp_night,
    "bg-gate.svg": gate_dawn,
    "bg-banquet.svg": banquet,
    "bg-fankuai.svg": fankuai,
    "bg-aftermath.svg": aftermath,
    "end-jade.svg": end_jade,
    "end-beacon.svg": end_beacon,
    "end-promise.svg": end_promise,
}

write_all(ART, sys.argv[1])
