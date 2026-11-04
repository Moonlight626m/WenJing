"""演出台本配图的公共笔墨：画布、渐变、山脊、飞雪、飞鸟、瓦檐。

每一卷的生成脚本（gen_runtu.py、gen_hongmen.py）都从这里取，画出来的图同一套纸纹和墨晕。
"""
import math

W, H = 1920, 1080


def doc(body: str, defs: str = "") -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice">
<defs>
<filter id="grain" x="0" y="0" width="100%" height="100%">
  <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed="11" stitchTiles="stitch"/>
  <feColorMatrix values="0 0 0 0 0.5  0 0 0 0 0.45  0 0 0 0 0.4  0 0 0 0.09 0"/>
</filter>
<filter id="ink" x="-5%" y="-5%" width="110%" height="110%">
  <feTurbulence type="fractalNoise" baseFrequency="0.008 0.03" numOctaves="3" seed="5"/>
  <feDisplacementMap in="SourceGraphic" scale="22"/>
</filter>
<filter id="inkSoft" x="-5%" y="-5%" width="110%" height="110%">
  <feTurbulence type="fractalNoise" baseFrequency="0.02 0.05" numOctaves="2" seed="9"/>
  <feDisplacementMap in="SourceGraphic" scale="8"/>
</filter>
<filter id="blur6"><feGaussianBlur stdDeviation="6"/></filter>
<filter id="blur18" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="18"/></filter>
<filter id="blur40" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="40"/></filter>
{defs}
</defs>
{body}
<rect width="{W}" height="{H}" filter="url(#grain)"/>
</svg>
'''


def lin(id_, stops, x2=0, y2=1):
    s = "".join(f'<stop offset="{o}" stop-color="{c}" stop-opacity="{a}"/>' for o, c, a in stops)
    return f'<linearGradient id="{id_}" x1="0" y1="0" x2="{x2}" y2="{y2}">{s}</linearGradient>'


def rad(id_, stops, cx=0.5, cy=0.5, r=0.5):
    s = "".join(f'<stop offset="{o}" stop-color="{c}" stop-opacity="{a}"/>' for o, c, a in stops)
    return f'<radialGradient id="{id_}" cx="{cx}" cy="{cy}" r="{r}">{s}</radialGradient>'


def ridge(rng, y0, amp, step, x0=-40, x1=W + 40, jitter=0.5):
    """一条山脊线：随机起伏，平滑成三次曲线，向下封闭到画底。"""
    pts = []
    x = x0
    y = y0
    while x <= x1:
        y = y0 + amp * math.sin(x / (step * 1.7) + rng.random()) * rng.uniform(0.4, 1) + rng.uniform(-amp, amp) * jitter
        pts.append((x, y))
        x += step * rng.uniform(0.7, 1.3)
    d = f"M{pts[0][0]:.0f} {pts[0][1]:.0f} "
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        mx = (ax + bx) / 2
        d += f"Q{ax:.0f} {ay:.0f} {mx:.0f} {(ay + by) / 2:.0f} "
    d += f"L{x1} {H} L{x0} {H} Z"
    return d


def snow(rng, n, color="#f4f6f8", rmin=1.2, rmax=4.2, ymax=H, opacity=(0.35, 0.9)):
    out = []
    for _ in range(n):
        x, y = rng.uniform(0, W), rng.uniform(0, ymax)
        r = rng.uniform(rmin, rmax)
        o = rng.uniform(*opacity)
        out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.1f}" fill="{color}" opacity="{o:.2f}"/>')
    return "".join(out)


def flying(x, y, s=1.0, color="#20242a", opacity=0.8):
    return (
        f'<path transform="translate({x} {y}) scale({s})" d="M-22 0 Q -10 -10 0 0 Q 10 -10 22 0 Q 10 -5 0 3 Q -10 -5 -22 0 Z" '
        f'fill="{color}" opacity="{opacity}"/>'
    )


def eave(x0, y0, x1, y1, depth=26, tiles=True, color="#14171c"):
    """一段瓦檐：深色檐口加一排瓦当。"""
    out = f'<path d="M{x0} {y0} L{x1} {y1} L{x1} {y1 + depth} L{x0} {y0 + depth} Z" fill="{color}"/>'
    if tiles:
        n = max(2, int(math.hypot(x1 - x0, y1 - y0) / 22))
        for i in range(n + 1):
            t = i / n
            x = x0 + (x1 - x0) * t
            y = y0 + (y1 - y0) * t + depth
            out += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="6" fill="{color}"/>'
    return out


def write_all(art, out_dir):
    """把一卷的全部配图写进 out_dir，打印每张的大小。"""
    from pathlib import Path

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in art.items():
        svg = fn()
        (out / name).write_text(svg, encoding="utf-8")
        print(f"{name}: {len(svg) // 1024} KB")
