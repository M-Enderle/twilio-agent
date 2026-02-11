import { redirect } from "@sveltejs/kit";
import { dev } from "$app/environment";

export async function GET({ cookies }) {
	if (!dev) {
		return new Response("Not available in production", { status: 403 });
	}

	cookies.set(
		"session",
		JSON.stringify({
			user: { name: "Dev User", email: "dev@localhost" },
			accessToken: "dev-token",
			expiresAt: Date.now() + 7 * 24 * 60 * 60 * 1000
		}),
		{
			path: "/",
			httpOnly: true,
			secure: false,
			sameSite: "lax",
			maxAge: 60 * 60 * 24 * 7
		}
	);

	throw redirect(302, "/");
}
