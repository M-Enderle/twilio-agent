import type { Handle } from "@sveltejs/kit";
import { dev } from "$app/environment";
import { env } from "$env/dynamic/private";

export const handle: Handle = async ({ event, resolve }) => {
	const response = await resolve(event);

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
	}

	response.headers.set(
		"Content-Security-Policy",
		[
			"default-src 'self'",
			"script-src 'self' 'unsafe-inline'",
			"style-src 'self' 'unsafe-inline'",
			"img-src 'self' data: https://*.tile.openstreetmap.org https://notdienststation.de",
			`connect-src ${connectSources.join(" ")}`,
			`media-src ${connectSources.join(" ")}`,
			"font-src 'self'",
			"frame-ancestors 'none'",
		].join("; ")
	);

	return response;
};
