import Link from "next/link";

export default function HomePage() {
  return (
    <main style={{ padding: 20, maxWidth: 760, margin: "0 auto" }}>
      <h1 style={{ marginTop: 0 }}>AI Golf Caddie</h1>
      <p>
        This is the Next.js frontend. Backend API should be served separately (FastAPI).
      </p>
      <ul>
        <li>
          <Link href="/settings">Settings (handicap + bag)</Link>
        </li>
        <li>
          <Link href="/rounds">Rounds (start/resume)</Link>
        </li>
      </ul>
    </main>
  );
}

