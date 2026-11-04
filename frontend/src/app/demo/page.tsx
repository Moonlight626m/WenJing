import { DemoHome } from "@/components/demo/demo-home";

export const metadata = {
  title: "演出模式",
  robots: { index: false, follow: false },
};

/**
 * 演出模式入口（`/demo`）：开卷标题页 → 书匣选卷。
 * 答辩与路演用：台本预先编排、离线可演，不登录、不碰后端。
 */
export default function DemoPage() {
  return <DemoHome />;
}
