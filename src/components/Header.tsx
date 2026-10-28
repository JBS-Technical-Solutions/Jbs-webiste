"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { AnimatePresence, motion, type Variants } from "motion/react";
import { useLenis } from "lenis/react";
import Logo from "./Logo";
import { easeInOut, easeOut } from "./motion/easing";
import { contactHref, contactLabel, nav, site, type NavItem } from "@/lib/site";

const menuItems: NavItem[] = [{ href: "/", label: "Home" }, ...nav, { href: contactHref, label: contactLabel }];

const list: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.07, delayChildren: 0.35 } },
};
const item: Variants = {
  hidden: { transform: "translateY(110%)" },
  visible: { transform: "translateY(0%)", transition: { duration: 0.9, ease: easeOut } },
};

export default function Header() {
  const pathname = usePathname();
  const lenis = useLenis();
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!open) return;
    lenis?.stop();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      lenis?.start();
      window.removeEventListener("keydown", onKey);
    };
  }, [open, lenis]);

  return (
    <>
      <header
        className={`fixed inset-x-0 top-0 z-50 border-b transition-colors duration-500 ${
          scrolled && !open ? "border-line/70 bg-paper/75 backdrop-blur-md" : "border-transparent"
        }`}
      >
        <div className="mx-auto grid h-20 max-w-7xl grid-cols-[auto_1fr] items-center gap-x-4 px-6 sm:grid-cols-[1fr_auto_1fr] sm:gap-x-0 lg:px-12">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls="site-menu"
            aria-label={open ? "Close menu" : "Open menu"}
            className="group flex items-center gap-3 justify-self-start py-2 text-xs font-semibold uppercase tracking-[0.25em]"
          >
            <span className="relative block h-3 w-7">
              <span
                className={`absolute left-0 top-0 h-px w-full bg-ink transition-transform duration-500 ${
                  open ? "translate-y-[5px] rotate-45" : ""
                }`}
              />
              <span
                className={`absolute bottom-0 left-0 h-px bg-ink transition-all duration-500 ${
                  open ? "w-full -translate-y-[6px] -rotate-45" : "w-full group-hover:w-2/3"
                }`}
              />
            </span>
            <span className="hidden sm:inline">{open ? "Close" : "Menu"}</span>
          </button>

          <Logo className="justify-self-start sm:justify-self-center" />

          <Link
            href={contactHref}
            onClick={() => setOpen(false)}
            className="hidden justify-self-end whitespace-nowrap rounded-full sm:inline-block bg-accent px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-white transition-colors hover:bg-accent-deep sm:px-5 sm:py-2.5 sm:text-xs"
          >
            {contactLabel}
          </Link>
        </div>
      </header>

      <AnimatePresence>
        {open && (
          <motion.div
            id="site-menu"
            key="menu"
            className="fixed inset-0 z-40 bg-paper"
            initial={{ clipPath: "inset(0% 0% 100% 0%)" }}
            animate={{ clipPath: "inset(0% 0% 0% 0%)" }}
            exit={{ clipPath: "inset(0% 0% 100% 0%)" }}
            transition={{ duration: 0.9, ease: easeInOut }}
          >
            <div className="mx-auto flex h-full max-w-7xl flex-col justify-between gap-12 px-6 pb-10 pt-28 lg:flex-row lg:items-end lg:px-12 lg:pb-16">
              <motion.ul variants={list} initial="hidden" animate="visible">
                {menuItems.map((link, i) => {
                  const active = pathname === link.href;
                  const className = "group flex items-baseline gap-4 py-1 sm:gap-6";
                  const label = (
                    <>
                      <span className="font-mono text-xs text-muted">0{i + 1}</span>
                      <span
                        className={`text-[clamp(2.5rem,7vw,5.5rem)] font-semibold uppercase leading-none tracking-[-0.03em] transition-all duration-500 group-hover:translate-x-3 group-hover:text-accent ${
                          active ? "text-accent" : ""
                        }`}
                      >
                        {link.label}
                      </span>
                    </>
                  );
                  return (
                    <li key={link.href} className="overflow-hidden">
                      <motion.div variants={item}>
                        {link.external ? (
                          <a href={link.href} onClick={() => setOpen(false)} className={className}>
                            {label}
                          </a>
                        ) : (
                          <Link
                            href={link.href}
                            onClick={() => setOpen(false)}
                            aria-current={active ? "page" : undefined}
                            className={className}
                          >
                            {label}
                          </Link>
                        )}
                      </motion.div>
                    </li>
                  );
                })}
              </motion.ul>

              <motion.div
                initial={{ opacity: 0, transform: "translateY(24px)" }}
                animate={{ opacity: 1, transform: "translateY(0px)", transition: { delay: 0.65, duration: 0.8, ease: easeOut } }}
                exit={{ opacity: 0, transition: { duration: 0.2 } }}
                className="space-y-6 text-sm lg:text-right"
              >
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-accent-deep">{site.tagline}</p>
                <p className="text-muted">{site.address}</p>
                <a
                  href={site.linkedin}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-block text-xs font-semibold uppercase tracking-[0.25em] hover:text-accent-deep"
                >
                  LinkedIn ↗
                </a>
              </motion.div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
