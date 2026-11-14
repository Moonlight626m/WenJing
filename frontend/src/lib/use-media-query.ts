"use client";

import { useCallback, useSyncExternalStore } from "react";

const serverSnapshot = () => false;

/**
 * 订阅一条媒体查询。服务端快照恒为 false：SSR 与首帧水合按「不匹配」渲染，
 * 水合后再切到真实值，不会出现水合不一致。
 *
 * subscribe/getSnapshot 用 useCallback 固定引用：内联函数每次渲染都是新的，
 * useSyncExternalStore 会因此每帧退订重订——调用方（游玩页）恰恰是每段流式台词
 * 都要渲染一次的组件。
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const mql = window.matchMedia(query);
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    },
    [query]
  );
  const getSnapshot = useCallback(
    () => window.matchMedia(query).matches,
    [query]
  );
  return useSyncExternalStore(subscribe, getSnapshot, serverSnapshot);
}
