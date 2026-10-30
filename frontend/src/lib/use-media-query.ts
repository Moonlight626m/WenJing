"use client";

import { useSyncExternalStore } from "react";

/**
 * 订阅一条媒体查询。服务端快照恒为 false：SSR 与首帧水合按「不匹配」渲染，
 * 水合后再切到真实值，不会出现水合不一致。
 */
export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (onChange) => {
      const mql = window.matchMedia(query);
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    },
    () => window.matchMedia(query).matches,
    () => false
  );
}
