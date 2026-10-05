"use client";

import { AnimatePresence, motion } from "motion/react";
import { useLenis } from "lenis/react";
import { useEffect, useState } from "react";
import { site } from "@/lib/site";
import { LogoLockup } from "../Logo";
import { easeInOut, easeOut } from "./easing";

export default function IntroLoader({ onDone }: { onDone: () => void }) {
  const [visible, setVisible] = useState(true);
  const lenis = useLenis();

  useEffect(() => {
    if (!visible) return;
    lenis?.stop();
    return () => lenis?.start();
  }, [lenis, visible]);

  useEffect(() => {
    if (visible || !lenis) return;
    const { hash } = window.location;
    if (hash && document.getElementById(hash.slice(1))) lenis.scrollTo(hash, { offset: -96, duration: 1.4 });
  }, [lenis, visible]);

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          key="intro"
          className="fixed inset-0 z-[100] flex flex-col items-center justify-center bg-paper"
          initial={{ clipPath: "inset(0% 0% 0% 0%)" }}
          exit={{ clipPath: "inset(0% 0% 100% 0%)" }}
          transition={{ duration: 1.1, ease: easeInOut }}
        >
          <motion.div
            role="img"
            aria-label={`${site.name} — ${site.tagline}`}
            initial={{ opacity: 0, scale: 0.9, filter: "blur(12px)" }}
            animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
            transition={{ duration: 1.2, ease: easeOut }}
          >
            <LogoLockup large />
          </motion.div>

          <div className="absolute bottom-16 left-1/2 h-px w-40 -translate-x-1/2 overflow-hidden bg-line">
            <motion.div
              className="h-full origin-left bg-accent"
              initial={{ scaleX: 0 }}
              animate={{ scaleX: 1 }}
              transition={{ delay: 0.3, duration: 1.7, ease: easeInOut }}
              onAnimationComplete={() => {
                setVisible(false);
                onDone();
              }}
            />
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
