import { ShowcaseGallery } from "@/components/showcase/showcase-gallery";

export const metadata = {
  title: "界面总览",
  // 内部评审页：不进搜索引擎
  robots: { index: false, follow: false },
};

/**
 * 纯前端界面总览（`/showcase`）：真实组件 + 假数据，不碰后端、不需要登录。
 * 用来评审版式与配色，也方便改样式时快速对一眼——不是产品功能页。
 */
export default function ShowcasePage() {
  return <ShowcaseGallery />;
}
