"use client";

import { useEffect, useRef } from "react";

/** 光尘颗数：够看出是一片，又不至于抢字幕的视线。 */
const MOTES = 34;

interface Mote {
  /** 横纵位置，按画布宽高的比例记，换尺寸时不用重算 */
  x: number;
  y: number;
  radius: number;
  /** 每毫秒上升多少个画布高度 */
  rise: number;
  sway: number;
  phase: number;
  color: string;
}

function spawn(colors: string[], anywhere: boolean): Mote {
  return {
    x: Math.random(),
    y: anywhere ? Math.random() : 1.04,
    radius: 0.6 + Math.random() * 1.6,
    rise: 0.000012 + Math.random() * 0.00003,
    sway: 0.006 + Math.random() * 0.014,
    phase: Math.random() * Math.PI * 2,
    color: colors[Math.floor(Math.random() * colors.length)],
  };
}

/**
 * 舞台光尘：青碧与泥金的细小光点自下而上漂，忽明忽暗。
 *
 * 一张 canvas、一个 rAF 循环，页面切到后台即停；颜色读舞台令牌，不另写死。
 * 只在特效「完整」档挂载（见 GameStage），简洁档与「减少动态效果」下不渲染。
 */
export function StageParticles() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;

    const style = getComputedStyle(canvas);
    const colors = ["--wj-glow-jade", "--wj-glow-gold"]
      .map((name) => style.getPropertyValue(name).trim())
      .filter(Boolean);
    if (colors.length === 0) return;

    const motes = Array.from({ length: MOTES }, () => spawn(colors, true));
    let width = 0;
    let height = 0;
    let frame = 0;
    let last = 0;

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = canvas!.clientWidth;
      height = canvas!.clientHeight;
      canvas!.width = Math.round(width * dpr);
      canvas!.height = Math.round(height * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function draw(now: number) {
      const dt = last ? Math.min(now - last, 48) : 16;
      last = now;
      ctx!.clearRect(0, 0, width, height);
      for (let i = 0; i < motes.length; i++) {
        const m = motes[i];
        m.y -= m.rise * dt;
        if (m.y < -0.04) {
          motes[i] = spawn(colors, false);
          continue;
        }
        const x = (m.x + Math.sin(now * 0.0004 + m.phase) * m.sway) * width;
        const y = m.y * height;
        // 越往上越淡，像光尘升进暗处
        const twinkle = 0.45 + 0.55 * Math.sin(now * 0.0012 + m.phase) ** 2;
        ctx!.globalAlpha = twinkle * Math.min(1, m.y * 1.6) * 0.75;
        ctx!.fillStyle = m.color;
        ctx!.shadowColor = m.color;
        ctx!.shadowBlur = 10;
        ctx!.beginPath();
        ctx!.arc(x, y, m.radius, 0, Math.PI * 2);
        ctx!.fill();
      }
      frame = requestAnimationFrame(draw);
    }

    function onVisibility() {
      cancelAnimationFrame(frame);
      if (document.visibilityState === "visible") {
        last = 0;
        frame = requestAnimationFrame(draw);
      }
    }

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    document.addEventListener("visibilitychange", onVisibility);
    frame = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return (
    <canvas
      ref={ref}
      aria-hidden
      className="pointer-events-none absolute inset-0 z-0 h-full w-full"
    />
  );
}
