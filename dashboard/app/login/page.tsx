"use client";

import { signIn } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError("");
    const form = new FormData(e.currentTarget);
    const res = await signIn("credentials", {
      username: String(form.get("username") ?? ""),
      password: String(form.get("password") ?? ""),
      redirect: false,
    });
    setLoading(false);
    if (res?.error) {
      setError("Invalid credentials");
      return;
    }
    router.push("/");
    router.refresh();
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm rounded-md border border-border bg-bg2 p-8"
      >
        <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.3em] text-gold">
          ADAI Systems
        </div>
        <h1 className="mb-6 text-2xl font-bold">Apex Algo</h1>

        <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-textdim">
          Username
        </label>
        <input
          name="username"
          autoComplete="username"
          className="mb-4 w-full rounded border border-border bg-bg3 px-3 py-2 text-sm outline-none focus:border-gold"
          required
        />

        <label className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-textdim">
          Password
        </label>
        <input
          name="password"
          type="password"
          autoComplete="current-password"
          className="mb-6 w-full rounded border border-border bg-bg3 px-3 py-2 text-sm outline-none focus:border-gold"
          required
        />

        {error && <p className="mb-4 text-sm text-down">{error}</p>}

        <button
          type="submit"
          disabled={loading}
          className="w-full rounded bg-gold py-2 text-sm font-bold text-black transition hover:bg-gold2 disabled:opacity-50"
        >
          {loading ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
