import { notFound } from "next/navigation";

import { findScript, SHELF } from "@/lib/demo/catalog";
import { DemoPlayer } from "@/components/demo/demo-player";

export const metadata = {
  title: "演出模式",
  robots: { index: false, follow: false },
};

export function generateStaticParams() {
  return SHELF.filter((s) => s.script !== null).map((s) => ({ slug: s.slug }));
}

export default async function DemoPlayPage({ params }: PageProps<"/demo/[slug]">) {
  const { slug } = await params;
  if (!findScript(slug)) notFound();
  return <DemoPlayer slug={slug} />;
}
