"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import { MotionConfig } from "motion/react";
import { ReactLenis } from "lenis/react";
import IntroLoader from "./IntroLoader";

const IntroContext = createContext(true);

export function useIntroDone() {
  return useContext(IntroContext);
}

export default function Providers({ children }: { children: ReactNode }) {
  const [introDone, setIntroDone] = useState(false);

  return (
    <MotionConfig reducedMotion="user">
      <ReactLenis root options={{ lerp: 0.09, anchors: { offset: -96 } }}>
        <IntroContext.Provider value={introDone}>
          {children}
          <IntroLoader onDone={() => setIntroDone(true)} />
        </IntroContext.Provider>
      </ReactLenis>
    </MotionConfig>
  );
}
