import type { ReactNode } from "react";

import "./globals.css";

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="phoneOuter">
          <div className="phoneFrame">
            {children}
          </div>
        </div>
      </body>
    </html>
  );
}

