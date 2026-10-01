import type { Metadata } from "next";
import CtaBanner from "@/components/CtaBanner";
import EquipmentDiagram from "@/components/EquipmentDiagram";
import RevealLines from "@/components/motion/RevealLines";
import Reveal from "@/components/motion/Reveal";
import { models } from "@/lib/models";

export const metadata: Metadata = {
  title: "Models",
  description:
    "Digital twin models built by JBS Technical Solutions for heat exchangers, methanol reactors and centrifugal pumps.",
};

const label = "text-xs font-semibold uppercase tracking-[0.3em] text-accent-deep";
const heading = "font-semibold uppercase leading-[0.92] tracking-[-0.035em]";

export default function ModelsPage() {
  return (
    <>
      <section className="mx-auto w-full max-w-7xl px-6 pb-12 pt-40 lg:px-12 lg:pt-48">
        <RevealLines as="p" className={label} lines={["Models"]} />
        <RevealLines
          as="h1"
          delay={0.1}
          className={`mt-6 text-[clamp(2.6rem,7vw,7rem)] ${heading}`}
          lines={[
            "Twins built for",
            <span key="critical">
              <span className="text-accent">critical</span> process
            </span>,
            "equipment.",
          ]}
        />
        <Reveal delay={0.4} className="mt-10 max-w-2xl">
          <p className="text-lg leading-relaxed text-muted">
            Each model combines live plant data, first-principles physics and machine learning — tailored to how that
            piece of equipment really behaves.
          </p>
        </Reveal>

        <Reveal delay={0.5} className="mt-12">
          <nav aria-label="Models on this page" className="flex flex-wrap gap-2">
            {models.map((model, i) => (
              <a
                key={model.slug}
                href={`#${model.slug}`}
                className="rounded-full border border-line bg-white px-4 py-2 text-sm transition-colors hover:border-accent hover:text-accent-deep"
              >
                <span className="mr-2 font-mono text-xs text-muted">0{i + 1}</span>
                {model.name}
              </a>
            ))}
          </nav>
        </Reveal>
      </section>

      {models.map((model, i) => (
        <section
          key={model.slug}
          id={model.slug}
          className="mx-auto grid w-full max-w-7xl scroll-mt-24 items-center gap-12 border-t border-line px-6 py-24 lg:grid-cols-2 lg:gap-20 lg:px-12"
        >
          <Reveal className={i % 2 ? "lg:order-2" : ""}>
            <div className="relative aspect-[4/3] overflow-hidden rounded-3xl border border-line bg-soft p-6 sm:p-10">
              <span className="absolute left-6 top-6 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.25em] text-muted sm:left-8 sm:top-8">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-accent opacity-60" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-accent" />
                </span>
                Digital twin
              </span>
              <span className="absolute right-6 top-6 font-mono text-xs text-muted sm:right-8 sm:top-8">0{i + 1}</span>
              <EquipmentDiagram kind={model.slug} label={`${model.name} schematic`} />
            </div>
          </Reveal>

          <div>
            <RevealLines as="p" className={label} lines={[model.category]} />
            <RevealLines
              as="h2"
              delay={0.1}
              className={`mt-5 text-[clamp(2.4rem,5vw,4.5rem)] ${heading}`}
              lines={[model.name]}
            />
            <Reveal delay={0.2}>
              <p className="mt-6 leading-relaxed text-muted">{model.description}</p>
            </Reveal>

            <Reveal delay={0.3} className="mt-10">
              <h3 className="text-xs font-semibold uppercase tracking-[0.25em] text-ink">What it tracks</h3>
              <ul className="mt-4 grid gap-x-6 border-t border-line sm:grid-cols-2">
                {model.tracks.map((item) => (
                  <li key={item} className="flex items-center gap-3 border-b border-line py-3 text-[15px]">
                    <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                    {item}
                  </li>
                ))}
              </ul>
            </Reveal>

            <Reveal delay={0.4} className="mt-10">
              <h3 className="text-xs font-semibold uppercase tracking-[0.25em] text-ink">What you get</h3>
              <ul className="mt-4 space-y-2">
                {model.outcomes.map((item) => (
                  <li key={item} className="flex gap-3 text-[15px] leading-relaxed">
                    <span aria-hidden="true" className="text-accent">→</span>
                    {item}
                  </li>
                ))}
              </ul>
            </Reveal>
          </div>
        </section>
      ))}

      <CtaBanner title="Need a twin for other equipment?" highlight="We'll build it." />
    </>
  );
}
