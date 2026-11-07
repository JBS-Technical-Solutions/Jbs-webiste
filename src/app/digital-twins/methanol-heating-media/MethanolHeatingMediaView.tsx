"use client";

import dynamic from "next/dynamic";

function LoadingTwin() {
  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-4 bg-black text-white/70">
      <span className="h-10 w-10 animate-spin rounded-full border-2 border-white/15 border-t-[#ff7a3d]" />
      <p className="text-xs font-semibold uppercase tracking-[0.25em]">Loading simulation</p>
    </div>
  );
}

const MethanolHeatingTwin = dynamic(() => import("@/components/meoh-heat/MethanolHeatingTwin"), {
  ssr: false,
  loading: LoadingTwin,
});

export default function MethanolHeatingMediaView() {
  return <MethanolHeatingTwin className="min-h-svh" />;
}
