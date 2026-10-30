import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "文境 Wenjing",
    template: "%s · 文境",
  },
  description: "语文课文情景演绎 · 进入课文，成为其中的人",
};

// 浏览器地址栏主题色：meta 读不到 CSS 变量，只能把 `--wj-canvas`（globals.css 的
// 册·亮 / 册·暗）抄一份；改令牌时记得同步这里。
export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f1f2ed" },
    { media: "(prefers-color-scheme: dark)", color: "#13171c" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN" className="h-full">
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
