import type { ReactNode } from "react";

import { RoundsSubNav } from "./RoundsSubNav";

export default function RoundsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="pageScrollLight" style={{ minHeight: "min(100dvh, var(--phoneH))", background: "#ffffff" }}>
      <RoundsSubNav />
      <div
        style={{
          padding: "16px 20px 28px",
          maxWidth: 960,
          margin: "0 auto",
          boxSizing: "border-box",
        }}
      >
        {children}
      </div>
    </div>
  );
}
