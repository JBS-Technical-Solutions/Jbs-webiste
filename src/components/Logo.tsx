import Image from "next/image";
import Link from "next/link";
import { site } from "@/lib/site";

type LockupProps = { inverse?: boolean; large?: boolean };

export function LogoLockup({ inverse = false, large = false }: LockupProps) {
  return (
    <span className={`flex items-center ${large ? "gap-4 sm:gap-6" : "gap-2.5 sm:gap-3"}`}>
      <Image
        src="/logo.png"
        alt=""
        width={1251}
        height={842}
        priority
        className={large ? "h-16 w-auto sm:h-28" : "h-10 w-auto sm:h-12"}
      />
      <span className="flex flex-col text-left leading-none">
        <span
          className={`whitespace-nowrap font-serif tracking-tight ${
            large ? "text-3xl sm:text-6xl" : "text-lg sm:text-xl"
          } ${inverse ? "text-white" : "text-ink"}`}
        >
          {site.name}
        </span>
        <span
          className={`whitespace-nowrap font-semibold uppercase text-accent-deep ${
            large
              ? "mt-2.5 text-[10px] tracking-[0.14em] sm:mt-4 sm:text-base"
              : "mt-1.5 text-[9px] tracking-[0.12em] sm:text-[10px]"
          }`}
        >
          {site.tagline}
        </span>
      </span>
    </span>
  );
}

type Props = { className?: string; inverse?: boolean };

export default function Logo({ className = "", inverse = false }: Props) {
  return (
    <Link href="/" className={`flex ${className}`} aria-label={`${site.name} — home`}>
      <LogoLockup inverse={inverse} />
    </Link>
  );
}
