import { clerkMiddleware } from "@clerk/nextjs/server";

// Pass-through only — this enables Clerk on the app but intentionally does NOT
// enforce auth at the edge.
//
// Why: we run a Clerk *development* instance behind Hugging Face Spaces'
// reverse proxy. Server-side session verification for a dev instance needs a
// cross-domain handshake to `<slug>.clerk.accounts.dev`, and the session
// cookie is short-lived. On a page refresh (after that cookie expires) the
// handshake can't reliably complete through HF's proxy, so `auth.protect()`
// would mistake a signed-in user for signed-out and redirect *every*
// navigation to sign-in — breaking the whole app until a fresh sign-in.
//
// Instead we enforce sign-in on the CLIENT (see AuthGate + the /studio pages),
// which reads the session straight from the browser and is reliable. Data
// stays protected regardless: every /api/* data call carries a Clerk bearer
// token that the FastAPI backend verifies.
export default clerkMiddleware();

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
