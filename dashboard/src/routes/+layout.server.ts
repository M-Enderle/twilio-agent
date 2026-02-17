import { redirect } from "@sveltejs/kit";
import { env } from "$env/dynamic/private";
import type { LayoutServerLoad } from "./$types";

export const load: LayoutServerLoad = async ({ cookies, url }) => {
	const apiUrl = env.API_URL || null;

	if (url.pathname.startsWith("/auth")) {
		return { user: null, accessToken: null, apiUrl };
	}

	const sessionCookie = cookies.get("session");
	if (!sessionCookie) {
		throw redirect(302, "/auth/login");
	}

	let session: { user: unknown; accessToken: string; expiresAt: number };
	try {
		session = JSON.parse(sessionCookie);
	} catch {
		cookies.delete("session", { path: "/" });
		throw redirect(302, "/auth/login");
	}

	if (!session.expiresAt || session.expiresAt < Date.now()) {
		cookies.delete("session", { path: "/" });
		throw redirect(302, "/auth/login");
	}

	return { user: session.user, accessToken: session.accessToken, apiUrl };
};
