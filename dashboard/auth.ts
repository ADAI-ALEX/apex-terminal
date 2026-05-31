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
        const username = String(credentials?.username ?? "").trim();
        const password = String(credentials?.password ?? "");
        const expectedUser = (process.env.DASHBOARD_USERNAME ?? "").trim();
        const expectedHash = process.env.DASHBOARD_PASSWORD_HASH ?? "";
        const expectedPlain = process.env.DASHBOARD_PASSWORD ?? "";

        if (!expectedUser || username !== expectedUser) return null;

        // Two ways to set the password (single-user tool):
        //   DASHBOARD_PASSWORD_HASH — bcrypt hash (more secure), OR
        //   DASHBOARD_PASSWORD      — plaintext (simpler; fine for a private tool).
        let valid = false;
        if (expectedHash) {
          valid = await compare(password, expectedHash);
        } else if (expectedPlain) {
          valid = password === expectedPlain;
        }

        return valid ? { id: "1", name: username } : null;
      },
    }),
  ],
});
