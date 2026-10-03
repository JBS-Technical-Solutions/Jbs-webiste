"use client";

import { motion, type SVGMotionProps } from "motion/react";
import type { EquipmentModel } from "@/lib/models";
import { easeInOut } from "./motion/easing";

type Kind = EquipmentModel["slug"];

const draw = {
  initial: { pathLength: 0, opacity: 0 },
  whileInView: { pathLength: 1, opacity: 1 },
  viewport: { once: true, margin: "0px 0px -15% 0px" },
};

function Line({ d, delay = 0, accent = false, ...rest }: { d: string; delay?: number; accent?: boolean } & SVGMotionProps<SVGPathElement>) {
  return (
    <motion.path
      d={d}
      fill="none"
      stroke="currentColor"
      strokeWidth={accent ? 2 : 1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={accent ? "text-accent" : "text-ink/70"}
      transition={{ duration: 1.6, delay, ease: easeInOut }}
      {...draw}
      {...rest}
    />
  );
}

function Flow({ d, delay = 0 }: { d: string; delay?: number }) {
  return (
    <motion.path
      d={d}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeDasharray="4 10"
      className="text-accent"
      initial={{ opacity: 0, strokeDashoffset: 0 }}
      whileInView={{ opacity: 1, strokeDashoffset: -56 }}
      viewport={{ once: true }}
      transition={{
        opacity: { duration: 0.6, delay: delay + 1.2 },
        strokeDashoffset: { duration: 2, repeat: Infinity, ease: "linear", delay: delay + 1.2 },
      }}
    />
  );
}

function HeatExchanger() {
  return (
    <>
      <Line d="M110 110 H290 A40 40 0 0 1 290 190 H110 A40 40 0 0 1 110 110 Z" />
      <Line d="M122 112 V188 M278 112 V188" delay={0.2} />
      <Line d="M142 110 V80 H162 V110 M190 190 V220 H210 V190" delay={0.3} />
      <Line d="M128 190 L122 236 H162 L156 190 M244 190 L238 236 H278 L272 190" delay={0.4} />
      <Line d="M30 150 H70 M330 150 H370" delay={0.5} />
      {[128, 141, 154, 167, 180].map((y, i) => (
        <Line key={y} d={`M122 ${y - 6} H278`} delay={0.6 + i * 0.08} accent />
      ))}
      <Flow d="M30 150 H70" />
      <Flow d="M330 150 H370" delay={0.2} />
      <Flow d="M152 60 V80" delay={0.1} />
      <Flow d="M200 220 V244" delay={0.3} />
    </>
  );
}

function MethanolReformer() {
  return (
    <>
      <Line d="M160 72 Q160 40 200 40 Q240 40 240 72 V228 Q240 260 200 260 Q160 260 160 228 Z" />
      <Line d="M200 40 V16 H262 M200 260 V294" delay={0.2} />
      <Line d="M170 252 L160 290 M230 252 L240 290" delay={0.3} />
      <Line d="M160 108 H240 M160 204 H240" delay={0.4} accent />
      {[128, 156, 184].map((y, i) => (
        <g key={y}>
          <Line d={`M240 ${y} H278`} delay={0.6 + i * 0.1} />
          <motion.circle
            cx={284}
            cy={y}
            r={5}
            className="fill-accent"
            initial={{ scale: 0 }}
            whileInView={{ scale: [0, 1.25, 1] }}
            viewport={{ once: true }}
            transition={{ duration: 0.6, delay: 1.4 + i * 0.12 }}
          />
        </g>
      ))}
      {Array.from({ length: 24 }, (_, i) => {
        const col = i % 6;
        const row = Math.floor(i / 6);
        return (
          <motion.circle
            key={i}
            cx={172 + col * 11.2 + (row % 2) * 5}
            cy={124 + row * 20}
            r={3}
            className="fill-accent/70"
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true }}
            transition={{ duration: 0.4, delay: 0.9 + i * 0.025 }}
          />
        );
      })}
      <Flow d="M262 16 H200 V40" />
      <Flow d="M200 260 V294" delay={0.3} />
    </>
  );
}

function Pump() {
  const vanes = Array.from({ length: 6 }, (_, i) => {
    const a = (i * Math.PI) / 3;
    const p = (r: number, off: number) =>
      `${(180 + r * Math.cos(a + off)).toFixed(1)} ${(170 + r * Math.sin(a + off)).toFixed(1)}`;
    return `M${p(12, 0)} Q${p(30, 0.15)} ${p(44, 0.65)}`;
  });

  return (
    <>
      <Line d="M200 113.4 A60 60 0 1 0 240 170" />
      <Line d="M200 114 V60 M240 170 V60 M188 60 H252" delay={0.2} />
      <Line d="M40 160 H121 M40 180 H121 M62 148 V192" delay={0.3} />
      <Line d="M240 176 H266" delay={0.4} />
      <Line d="M266 142 H340 A6 6 0 0 1 346 148 V202 A6 6 0 0 1 340 208 H266 Z M286 142 V208 M306 142 V208 M326 142 V208" delay={0.5} />
      <Line d="M90 254 H360 M150 228 L140 254 M212 228 L222 254 M286 208 V254 M326 208 V254" delay={0.6} />
      <motion.g
        style={{ transformBox: "fill-box", transformOrigin: "center" }}
        animate={{ rotate: 360 }}
        transition={{ duration: 4, repeat: Infinity, ease: "linear" }}
      >
        <Line d="M180 160 A10 10 0 1 1 179.9 160" delay={0.6} accent />
        {vanes.map((d, i) => (
          <Line key={i} d={d} delay={0.8 + i * 0.06} accent />
        ))}
      </motion.g>
      <Flow d="M40 170 H120" />
      <Flow d="M220 114 V40" delay={0.3} />
    </>
  );
}

const diagrams: Record<Kind, () => React.JSX.Element> = {
  "heat-exchanger": HeatExchanger,
  "methanol-reformer": MethanolReformer,
  pump: Pump,
};

export default function EquipmentDiagram({ kind, label }: { kind: Kind; label: string }) {
  const Diagram = diagrams[kind];
  return (
    <svg viewBox="0 0 400 300" role="img" aria-label={label} className="h-full w-full">
      <Diagram />
    </svg>
  );
}
