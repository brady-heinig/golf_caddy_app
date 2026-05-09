"use client";

import type { CSSProperties } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

function tabStyle(active: boolean): CSSProperties {
  return {
    fontWeight: active ? 800 : 600,
    color: active ? "#0b1220" : "rgba(11,18,32,0.62)",
    textDecoration: "none",
    padding: "10px 0",
    borderBottom: active ? "2px solid #16a34a" : "2px solid transparent",
    marginBottom: -1,
  };
}

export function RoundsSubNav() {
  const pathname = usePathname();
  const shotTab = pathname === "/rounds/shot-history";
  const roundsTab =
    !shotTab && (pathname === "/rounds" || (pathname ? /^\/rounds\/\d+/.test(pathname) : false));

  return (
    <header
      style={{
        position: "sticky",
        top: 0,
        zIndex: 5,
        background: "#ffffff",
        borderBottom: "1px solid rgba(11,18,32,0.12)",
      }}
    >
      <nav
        aria-label="Past rounds sections"
        style={{
          display: "flex",
          gap: 22,
          maxWidth: 960,
          margin: "0 auto",
          padding: "0 20px",
          boxSizing: "border-box",
        }}
      >
        <Link href="/rounds" style={tabStyle(roundsTab)}>
          Rounds
        </Link>
        <Link href="/rounds/shot-history" style={tabStyle(shotTab)}>
          Shot history
        </Link>
      </nav>
    </header>
  );
}
