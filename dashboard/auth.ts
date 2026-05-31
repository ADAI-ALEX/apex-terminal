import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import { compare } from "bcryptjs";
import { authConfig } from "./auth.config";

export const { handlers, auth, signIn, signOut } = NextAuth({
  ...authConfig,
  providers: [
    Credentials({
      credentials: {
        username: { label: "Username", type: "text" },
        password: { label: "Password", type: "password" },
      },
      async authorize(credentials) {
        const username = String(credentials?.username ?? "");
        const password = String(credentials?.password ?? "");
        const expectedUser = process.env.DASHBOARD_USERNAME ?? "";
        const expectedHash = process.env.DASHBOARD_PASSWORD_HASH ?? "";

        if (!expectedUser || !expectedHash) return null;
        if (username !== expectedUser) return null;

        const valid = await compare(password, expectedHash);
        return valid ? { id: "1", name: username } : null;
      },
    }),
  ],
});
