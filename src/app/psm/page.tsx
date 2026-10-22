import type { Metadata } from "next";
import RevealLines from "@/components/motion/RevealLines";
import Reveal from "@/components/motion/Reveal";

export const metadata: Metadata = {
  title: "PSM",
  description:
    "JBS Technical Solutions works on workflow digitization for key Process Safety Management elements under OSHA 29 CFR 1910.119.",
};

/** Selected OSHA 29 CFR 1910.119 elements — titles only for later expansion. */
const psmElements = [
  "Process safety information",
  "Process hazard analysis",
  "Mechanical integrity",
  "Management of change",
  "Incident investigation",
];

const label = "text-xs font-semibold uppercase tracking-[0.3em] text-accent-deep";
const heading = "font-semibold uppercase leading-[0.92] tracking-[-0.035em]";

export default function PsmPage() {
  return (
    <section className="mx-auto w-full max-w-7xl px-6 pb-28 pt-40 lg:px-12 lg:pt-48">
      <RevealLines as="p" className={label} lines={["Process Safety Management"]} />
      <RevealLines
        as="h1"
        delay={0.1}
        className={`mt-6 text-[clamp(2.6rem,7vw,7rem)] ${heading}`}
        lines={[
          <span key="psm">
            <span className="text-accent">PSM</span>
          </span>,
        ]}
      />
      <Reveal delay={0.35} className="mt-10 max-w-2xl">
        <p className="text-lg leading-relaxed text-muted">
          Selected Process Safety Management elements under OSHA{" "}
          <span className="text-ink">29 CFR 1910.119</span>. JBS works in the area of{" "}
          <span className="text-ink">workflow digitization</span> for these elements.
        </p>
      </Reveal>

      <Reveal delay={0.45} className="mt-16 border-t border-line pt-12">
        <h2 className={`text-[clamp(1.75rem,3.5vw,2.75rem)] ${heading}`}>PSM elements</h2>
        <ul className="mt-10 space-y-0 border-t border-line">
          {psmElements.map((element, i) => (
            <li
              key={element}
              className="flex items-baseline gap-4 border-b border-line py-5 sm:gap-6 sm:py-6"
            >
              <span className="shrink-0 font-mono text-xs text-muted">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span className="text-lg font-medium tracking-tight sm:text-xl">{element}</span>
            </li>
          ))}
        </ul>
      </Reveal>
    </section>
  );
}
