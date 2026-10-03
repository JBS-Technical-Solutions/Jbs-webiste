import Image from "next/image";
import Link from "next/link";
import { site } from "@/lib/site";

type Props = { className?: string; hideTextOnMobile?: boolean };

export default function Logo({ className = "", hideTextOnMobile = false }: Props) {
  return (
    <Link href="/" className={`flex items-center gap-3 ${className}`} aria-label={`${site.name} — home`}>
      <Image src="/logo.png" alt="" width={1251} height={842} priority className="h-11 w-auto sm:h-12" />
      <span className={`flex-col text-left leading-none ${hideTextOnMobile ? "hidden sm:flex" : "flex"}`}>
        <span className="whitespace-nowrap font-serif text-xl tracking-tight text-ink">{site.name}</span>
        <span className="mt-1.5 whitespace-nowrap text-[10px] font-semibold uppercase tracking-[0.12em] text-accent-deep">
          {site.tagline}
        </span>
      </span>
    </Link>
  );
}
