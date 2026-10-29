import Link from "next/link";
import Logo from "./Logo";
import Reveal from "./motion/Reveal";
import { contactHref, contactLabel, nav, site } from "@/lib/site";

export default function Footer() {
  return (
    <footer className="border-t border-line bg-soft/60">
      <div className="mx-auto grid max-w-7xl gap-12 px-6 py-16 md:grid-cols-[1.6fr_1fr_1.2fr] lg:px-12">
        <Reveal>
          <Logo />
          <p className="mt-6 max-w-xs text-sm leading-relaxed text-muted">
            Data science, digital twins and process engineering for the energy and chemical industries.
          </p>
        </Reveal>

        <Reveal delay={0.1}>
          <h2 className="text-xs font-semibold uppercase tracking-[0.25em] text-muted">Company</h2>
          <ul className="mt-5 space-y-2.5 text-[15px]">
            {nav.map((item) => (
              <li key={item.href}>
                {item.external ? (
                  <a href={item.href} className="transition-colors hover:text-accent-deep">
                    {item.label}
                  </a>
                ) : (
                  <Link href={item.href} className="transition-colors hover:text-accent-deep">
                    {item.label}
                  </Link>
                )}
              </li>
            ))}
            <li>
              <Link href={contactHref} className="transition-colors hover:text-accent-deep">
                {contactLabel}
              </Link>
            </li>
          </ul>
        </Reveal>

        <Reveal delay={0.2}>
          <h2 className="text-xs font-semibold uppercase tracking-[0.25em] text-muted">Contact</h2>
          <ul className="mt-5 space-y-2.5 text-[15px]">
            <li className="text-muted">{site.address}</li>
            <li>
              <a
                href={site.linkedin}
                target="_blank"
                rel="noopener noreferrer"
                className="transition-colors hover:text-accent-deep"
              >
                LinkedIn ↗
              </a>
            </li>
          </ul>
        </Reveal>
      </div>

      <div className="border-t border-line">
        <div className="mx-auto max-w-7xl px-6 py-5 text-xs uppercase tracking-[0.15em] text-muted lg:px-12">
          © {new Date().getFullYear()} {site.name}. All rights reserved.
        </div>
      </div>
    </footer>
  );
}
