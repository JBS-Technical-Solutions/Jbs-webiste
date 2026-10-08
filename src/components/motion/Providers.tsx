"use client";

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { cancelFrame, frame, MotionConfig } from "motion/react";
import { ReactLenis, type LenisRef } from "lenis/react";
import IntroLoader from "./IntroLoader";

const IntroContext = createContext(true);

export function useIntroDone() {
  return useContext(IntroContext);
}

export default function Providers({ children }: { children: ReactNode }) {
  const [introDone, setIntroDone] = useState(false);
  const lenisRef = useRef<LenisRef>(null);

  // Drive Lenis from Motion's frame loop so scroll position and scroll-linked transforms update in the same frame.
  useEffect(() => {
    function update({ timestamp }: { timestamp: number }) {
      lenisRef.current?.lenis?.raf(timestamp);
    }
    frame.update(update, true);
    return () => cancelFrame(update);
  }, []);

  return (
    <MotionConfig reducedMotion="user">
      <ReactLenis root ref={lenisRef} options={{ autoRaf: false, lerp: 0.08, anchors: { offset: -96 } }}>
        <IntroContext.Provider value={introDone}>
          {children}
          <IntroLoader onDone={() => setIntroDone(true)} />
        </IntroContext.Provider>
      </ReactLenis>
    </MotionConfig>
  );
}
