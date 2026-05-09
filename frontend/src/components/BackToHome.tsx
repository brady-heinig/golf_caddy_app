"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function BackToHome() {
  const pathname = usePathname();
  if (!pathname || pathname === "/") return null;

  return (
    <Link href="/" className="backToHome" aria-label="Back to home" title="Home">
      <svg className="backToHomeSvg" width="22" height="22" viewBox="0 0 24 24" aria-hidden>
        <path
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M15 18l-6-6 6-6"
        />
      </svg>
    </Link>
  );
}
