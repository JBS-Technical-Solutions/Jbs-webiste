import type { Metadata } from "next";
import MethanolHeatingMediaView from "./MethanolHeatingMediaView";

export const metadata: Metadata = {
  title: "Methanol Heating Media Model",
  description:
    "Methanol decomposition digital twin with heating-media temperature as a live plant input.",
  robots: { index: false, follow: false },
};

export default function MethanolHeatingMediaPage() {
  return <MethanolHeatingMediaView />;
}
