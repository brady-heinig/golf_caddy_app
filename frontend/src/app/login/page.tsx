"use client";

import { useState } from "react";

import { apiFetch } from "@/lib/api";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setOk(false);
    try {
      await apiFetch("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password })
      });
      setOk(true);
    } catch (err: any) {
      setError(err?.message || "Login failed");
    }
  }

  return (
    <main style={{ padding: 20, maxWidth: 520, margin: "0 auto" }}>
      <h1 style={{ marginTop: 0 }}>Login</h1>
      <form onSubmit={onSubmit} style={{ display: "grid", gap: 12 }}>
        <label>
          Username
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            style={{ width: "100%", padding: 10, marginTop: 6 }}
          />
        </label>
        <label>
          Password
          <input
            value={password}
            type="password"
            onChange={(e) => setPassword(e.target.value)}
            style={{ width: "100%", padding: 10, marginTop: 6 }}
          />
        </label>
        <button type="submit" style={{ padding: 12 }}>
          Sign in
        </button>
        {ok ? <p style={{ color: "green" }}>Logged in.</p> : null}
        {error ? <p style={{ color: "crimson" }}>{error}</p> : null}
      </form>
      <p style={{ marginTop: 16, fontSize: 14, opacity: 0.8 }}>
        API base: <code>{process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"}</code>
      </p>
    </main>
  );
}

