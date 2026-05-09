import type { ReactNode } from "react";

import { BackToHome } from "@/components/BackToHome";

import "./globals.css";

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

