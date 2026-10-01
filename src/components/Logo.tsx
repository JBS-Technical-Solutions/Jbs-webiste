import Image from "next/image";
import Link from "next/link";

type Props = { className?: string; showName?: boolean };

export default function Logo({ className = "", showName = true }: Props) {
  return (
    <Link href="/" className={`flex items-center gap-3 ${className}`} aria-label="JBS Technical Solutions — home">
      <Image
        src="/logo.png"
        alt=""
        width={1251}
        height={842}
        priority
        className={showName ? "h-9 w-auto" : "h-12 w-auto"}
      />
      {showName && (
        <>
          <span aria-hidden="true" className="hidden h-6 w-px bg-line sm:block" />
          <span className="hidden whitespace-nowrap font-serif text-xl tracking-tight text-ink sm:inline">
            JBS Technical Solutions
          </span>
        </>
      )}
    </Link>
  );
}
