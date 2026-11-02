"use client";

import type { ReactNode } from "react";
import { LazyMotion, MotionConfig, domAnimation } from "motion/react";

/**
 * motion 的根：按需只加载 DOM 动画特性（`m.*` 组件，strict 模式下误用 `motion.*`
 * 会直接报错，防止整包被打进来），并让「减少动态效果」的系统设置关掉位移类动画。
 *
 * 用到 `m.*` 的子树都要包在它里面——没有它，`m.*` 会停在 `initial` 那一帧不动。
 */
export function MotionRoot({ children }: { children: ReactNode }) {
  return (
    <LazyMotion features={domAnimation} strict>
      <MotionConfig reducedMotion="user">{children}</MotionConfig>
    </LazyMotion>
  );
}
