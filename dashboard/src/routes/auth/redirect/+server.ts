import { redirect } from "@sveltejs/kit";
import { generateState, generateCodeVerifier } from "arctic";
import { getOAuth2Client, getAuthorizeEndpoint, CodeChallengeMethod } from "$lib/server/auth";

export async function GET({ cookies }) {
	const state = generateState();
	const codeVerifier = generateCodeVerifier();

	cookies.set("oauth_state", state, {
		path: "/",
		httpOnly: true,
		secure: true,
		sameSite: "lax",
		maxAge: 600
	});
	cookies.set("oauth_code_verifier", codeVerifier, {
		path: "/",
		httpOnly: true,
		secure: true,
		sameSite: "lax",
		maxAge: 600
	});

	const client = getOAuth2Client();
	const url = client.createAuthorizationURLWithPKCE(
		getAuthorizeEndpoint(),
		state,
		CodeChallengeMethod.S256,
		codeVerifier,
		["openid", "profile", "email"]
	);

	throw redirect(302, url.toString());
}
