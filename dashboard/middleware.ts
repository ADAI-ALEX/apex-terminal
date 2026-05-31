import NextAuth from "next-auth";
import { authConfig } from "./auth.config";

// Middleware uses the edge-safe config (no bcrypt) and the `authorized` callback
// to gate every matched route.
export default NextAuth(authConfig).auth;

export const config = {
  // Protect everything except NextAuth's own endpoints and static assets.
  matcher: ["/((?!api/auth|_next/static|_next/image|favicon.ico).*)"],
};
