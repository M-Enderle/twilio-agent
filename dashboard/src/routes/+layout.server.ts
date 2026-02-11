import { redirect } from "@sveltejs/kit";
import type { LayoutServerLoad } from "./$types";

export const load: LayoutServerLoad = async ({ cookies, url }) => {
	if (url.pathname.startsWith("/auth")) {
		return { user: null, accessToken: null };
	}

	const sessionCookie = cookies.get("session");
	if (!sessionCookie) {
		throw redirect(302, "/auth/login");
	}

	const session = JSON.parse(sessionCookie);

	if (session.expiresAt < Date.now()) {
		cookies.delete("session", { path: "/" });
		throw redirect(302, "/auth/login");
	}

	return { user: session.user, accessToken: session.accessToken };
};
