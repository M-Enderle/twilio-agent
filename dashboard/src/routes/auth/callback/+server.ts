import { redirect } from "@sveltejs/kit";
import { getOAuth2Client, getTokenEndpoint, getUserinfoEndpoint } from "$lib/server/auth";

export async function GET({ url, cookies }) {
	const code = url.searchParams.get("code");
	const state = url.searchParams.get("state");
	const storedState = cookies.get("oauth_state");
	const codeVerifier = cookies.get("oauth_code_verifier");

	if (!code || !state || state !== storedState || !codeVerifier) {
		return new Response("Invalid OAuth callback", { status: 400 });
	}

	const client = getOAuth2Client();
	const tokens = await client.validateAuthorizationCode(
		getTokenEndpoint(),
		code,
		codeVerifier
	);

	const userResponse = await fetch(getUserinfoEndpoint(), {
		headers: { Authorization: `Bearer ${tokens.accessToken()}` }
	});
	const user = await userResponse.json();

	cookies.set(
		"session",
		JSON.stringify({
			user: { name: user.name, email: user.email },
			accessToken: tokens.accessToken(),
			expiresAt: Date.now() + 7 * 24 * 60 * 60 * 1000
		}),
		{
			path: "/",
			httpOnly: true,
			secure: true,
			sameSite: "lax",
			maxAge: 60 * 60 * 24 * 7
		}
	);

	cookies.delete("oauth_state", { path: "/" });
	cookies.delete("oauth_code_verifier", { path: "/" });

	throw redirect(302, "/");
}
