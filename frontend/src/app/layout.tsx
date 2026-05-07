import type { ReactNode } from "react";
import Link from "next/link";

import "./globals.css";

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="appShell">
          <header className="topBar">
            <div className="topBarInner">
              <div className="brand">
                <div className="brandTitle">AI Golf Caddie</div>
                <div className="brandSub">Course-ready advice: distance, wind, hazards</div>
              </div>
              <nav className="nav" aria-label="Primary navigation">
                <Link href="/">Home</Link>
                <Link href="/settings">Settings</Link>
                <Link href="/rounds">Rounds</Link>
              </nav>
            </div>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}

