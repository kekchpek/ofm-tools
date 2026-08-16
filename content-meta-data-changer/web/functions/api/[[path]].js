/**
 * Proxy /api/* from Cloudflare Pages to the Railway API.
 *
 * Why this exists: the frontend (pages.dev) and the API (railway.app) are
 * separate sites, so the session cookie is a third-party cookie. Mobile Safari
 * — and Chrome on iOS, which uses WebKit — block those outright, so sign-in
 * completes and then every request comes back 401. Routing API calls through
 * the Pages origin makes the cookie first-party and the problem disappears.
 *
 * It also removes the need for CORS entirely, since the browser only ever
 * talks to one origin.
 *
 * Set API_ORIGIN in the Pages project (e.g. https://your-api.up.railway.app).
 *
 * Caveat: Cloudflare caps a Worker request body at 100 MB on Free/Pro plans,
 * so uploads larger than that must not go through here. A custom domain
 * shared by both services avoids both the cookie problem and this limit.
 */

/** Hop-by-hop headers that must not be forwarded. */
const STRIP = new Set(["connection", "keep-alive", "transfer-encoding", "upgrade"]);

export async function onRequest(context) {
  const { request, env } = context;

  const apiOrigin = (env.API_ORIGIN || "").replace(/\/+$/, "");
  if (!apiOrigin) {
    return new Response(
      JSON.stringify({
        error:
          "API_ORIGIN is not set on this Pages project, so /api requests cannot be proxied.",
        code: "api_origin_missing",
      }),
      { status: 500, headers: { "content-type": "application/json" } },
    );
  }

  const incoming = new URL(request.url);
  const target = `${apiOrigin}${incoming.pathname}${incoming.search}`;

  const headers = new Headers(request.headers);
  for (const name of STRIP) {
    headers.delete(name);
  }
  // Let the API build absolute URLs against the public host, not its own.
  headers.set("X-Forwarded-Host", incoming.host);
  headers.set("X-Forwarded-Proto", incoming.protocol.replace(":", ""));

  const proxied = new Request(target, {
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
    // The OAuth callback answers with a redirect that the browser must follow
    // itself; following it here would swallow the Set-Cookie header.
    redirect: "manual",
  });

  const response = await fetch(proxied);

  // Rebuild so Set-Cookie survives and the body streams through unchanged.
  const outgoing = new Headers(response.headers);
  for (const name of STRIP) {
    outgoing.delete(name);
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers: outgoing,
  });
}
