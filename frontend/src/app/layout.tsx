import type { Metadata } from "next";
import type { ReactNode } from "react";

import { BackToHome } from "@/components/BackToHome";

import "./globals.css";

export const metadata: Metadata = {
  title: "ForeAI: An AI Golf Caddie",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="phoneOuter">
          <div className="phoneFrame">
            <BackToHome />
            {children}
          </div>
        </div>
      </body>
    </html>
  );
}

