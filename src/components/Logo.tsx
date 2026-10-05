import Image from "next/image";
import Link from "next/link";
import { site } from "@/lib/site";

type Props = { className?: string; inverse?: boolean };

export default function Logo({ className = "", inverse = false }: Props) {
  return (
    <Link href="/" className={`flex items-center gap-2.5 sm:gap-3 ${className}`} aria-label={`${site.name} — home`}>
      <Image src="/logo.png" alt="" width={1251} height={842} priority className="h-10 w-auto sm:h-12" />
      <span className="flex flex-col text-left leading-none">
        <span
          className={`whitespace-nowrap font-serif text-lg tracking-tight sm:text-xl ${inverse ? "text-white" : "text-ink"}`}
        >
          {site.name}
        </span>
        <span className="mt-1.5 whitespace-nowrap text-[9px] font-semibold uppercase tracking-[0.12em] text-accent-deep sm:text-[10px]">
          {site.tagline}
        </span>
      </span>
    </Link>
  );
}
