import type { Handle } from "@sveltejs/kit";
import { dev } from "$app/environment";
import { env } from "$env/dynamic/private";
import { logger } from "$lib/server/logger";

export const handle: Handle = async ({ event, resolve }) => {
	const start = Date.now();
	const response = await resolve(event, {
		transformPageChunk: ({ html }) => {
			// Inject API_URL into <head> so it's available before any SvelteKit
			// JS runs. Without this, child components can fire API calls during
			// hydration before the layout sets window.__API_URL__, causing them
			// to fall back to hostname:8000 which the CSP blocks.
			if (env.API_URL) {
				return html.replace(
					"<head>",
					`<head><script>window.__API_URL__="${env.API_URL}"</script>`
				);
			}
			return html;
		},
	});
	const duration = Date.now() - start;

	logger.info(
		`${event.request.method} ${event.url.pathname} ${response.status} ${duration}ms`
	);

	response.headers.set("X-Frame-Options", "DENY");
	response.headers.set("X-Content-Type-Options", "nosniff");
	response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
	response.headers.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");

	// Build connect-src dynamically: allow the API backend + OSRM router
	const connectSources = ["'self'", "https://router.project-osrm.org"];
	if (env.API_URL) {
		try {
			const apiOrigin = new URL(env.API_URL).origin;
			connectSources.push(apiOrigin);
		} catch {
			// Invalid URL, skip
		}
	}
	if (dev) {
		// In dev, the SPA falls back to same-hostname:8000 for the API
		connectSources.push("http://localhost:8000");
		// Vite HMR uses websockets on the dev server
		connectSources.push("ws://localhost:*");
		// Allow dev tunnels (e.g. VS Code port forwarding)
		connectSources.push("https://*.devtunnels.ms:*");
	}

	response.headers.set(
		"Content-Security-Policy",
		[
			"default-src 'self'",
			"script-src 'self' 'unsafe-inline'",
			"style-src 'self' 'unsafe-inline'",
			"img-src 'self' data: https://*.tile.openstreetmap.org https://notdienststation.de",
			`connect-src ${connectSources.join(" ")}`,
			`media-src blob: ${connectSources.join(" ")}`,
			"font-src 'self'",
			"frame-ancestors 'none'",
		].join("; ")
	);

	return response;
};
