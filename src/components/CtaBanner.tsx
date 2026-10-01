import Link from "next/link";
import Reveal from "./motion/Reveal";
import { enquireHref } from "@/lib/site";

type Props = { title?: string; highlight?: string };

export default function CtaBanner({ title = "Have a process challenge?", highlight = "Let's talk." }: Props) {
  return (
    <section className="px-6 pb-24 lg:px-12">
      <Reveal className="mx-auto max-w-7xl">
        <div className="flex flex-col items-start gap-8 rounded-3xl bg-ink px-8 py-16 text-paper sm:px-14 md:flex-row md:items-center md:justify-between">
          <h2 className="text-[clamp(2rem,4.5vw,3.75rem)] font-semibold uppercase leading-[0.92] tracking-[-0.035em]">
            {title}
            <br />
            <span className="text-peach">{highlight}</span>
          </h2>
          <Link
            href={enquireHref}
            className="shrink-0 rounded-full bg-accent px-8 py-4 text-xs font-semibold uppercase tracking-[0.18em] text-white transition-colors hover:bg-accent-deep"
          >
            Enquire
          </Link>
        </div>
      </Reveal>
    </section>
  );
}
