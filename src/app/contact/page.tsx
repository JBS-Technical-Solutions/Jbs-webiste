import type { Metadata } from "next";
import ContactForm from "@/components/ContactForm";
import RevealLines from "@/components/motion/RevealLines";
import Reveal from "@/components/motion/Reveal";
import { contactLabel, site } from "@/lib/site";

export const metadata: Metadata = {
  title: contactLabel,
  description: "Tell us about your process challenge — the JBS Technical Solutions team will get back to you.",
};

export default function ContactPage() {
  return (
    <section className="mx-auto grid w-full max-w-7xl gap-16 px-6 pb-28 pt-40 lg:grid-cols-[1fr_1.3fr] lg:gap-24 lg:px-12 lg:pt-48">
      <div>
        <RevealLines as="p" className="text-xs font-semibold uppercase tracking-[0.3em] text-accent-deep" lines={[contactLabel]} />
        <RevealLines
          as="h1"
          delay={0.1}
          className="mt-6 text-[clamp(2.6rem,5.5vw,5.5rem)] font-semibold uppercase leading-[0.92] tracking-[-0.035em]"
          lines={[
            "Let's talk",
            "about your",
            <span key="process" className="text-accent">
              process.
            </span>,
          ]}
        />
        <Reveal delay={0.4} className="mt-8 max-w-sm">
          <p className="text-lg leading-relaxed text-muted">
            Share a few details and our engineers will get back to you shortly.
          </p>
        </Reveal>

        <Reveal delay={0.5}>
          <dl className="mt-14 space-y-6 border-t border-line pt-8">
            <div>
              <dt className="text-xs font-semibold uppercase tracking-[0.25em] text-muted">Headquarters</dt>
              <dd className="mt-1.5 text-lg">{site.address}</dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-[0.25em] text-muted">LinkedIn</dt>
              <dd className="mt-1.5">
                <a
                  href={site.linkedin}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-lg transition-colors hover:text-accent-deep"
                >
                  JBS Technical Solutions ↗
                </a>
              </dd>
            </div>
          </dl>
        </Reveal>
      </div>

      <Reveal delay={0.3}>
        <ContactForm />
      </Reveal>
    </section>
  );
}
