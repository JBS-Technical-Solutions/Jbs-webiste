"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import Footer from "./Footer";
import Header from "./Header";
import { isHiddenTwinPath } from "@/lib/hidden-twins";

/** Skips site chrome on URL-only twin pages so the simulation fills the viewport. */
export default function SiteChrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  if (isHiddenTwinPath(pathname)) {
    return <main className="min-h-full flex-1">{children}</main>;
  }

  return (
    <>
      <Header />
      <main className="flex flex-1 flex-col">{children}</main>
      <Footer />
    </>
  );
}
