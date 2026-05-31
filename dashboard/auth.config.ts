import type { NextAuthConfig } from "next-auth";

/**
 * Edge-safe auth config shared by middleware and the full auth setup.
 * No bcrypt / Node APIs here so it can run in middleware.
 */
export const authConfig = {
  pages: { signIn: "/login" },
  session: { strategy: "jwt", maxAge: 8 * 60 * 60 }, // 8 hours
  callbacks: {
    authorized({ auth, request: { nextUrl } }) {
      const isLoggedIn = !!auth?.user;
      const isOnLogin = nextUrl.pathname.startsWith("/login");
      if (isOnLogin) {
        if (isLoggedIn) return Response.redirect(new URL("/", nextUrl));
        return true;
      }
      return isLoggedIn; // every other matched route requires a session
    },
  },
  providers: [], // defined in auth.ts (Node runtime)
} satisfies NextAuthConfig;
