"use client";

import Image, { type StaticImageData } from "next/image";
import { useRef } from "react";
import { motion, useScroll, useTransform } from "motion/react";

type Props = { src: StaticImageData; alt: string; className?: string; imageClassName?: string; sizes?: string };

export default function ParallaxImage({ src, alt, className = "", imageClassName = "", sizes = "100vw" }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start end", "end start"] });
  const y = useTransform(scrollYProgress, [0, 1], ["-12%", "12%"]);
  const scale = useTransform(scrollYProgress, [0, 0.5, 1], [1.15, 1.05, 1.15]);

  return (
    <div ref={ref} className={`relative overflow-hidden ${className}`}>
      <motion.div style={{ y, scale }} className="absolute inset-x-0 -inset-y-[14%]">
        <Image src={src} alt={alt} fill sizes={sizes} placeholder="blur" className={`object-cover ${imageClassName}`} />
      </motion.div>
    </div>
  );
}
