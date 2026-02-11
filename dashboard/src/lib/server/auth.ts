import { OAuth2Client, CodeChallengeMethod } from "arctic";
import { env } from "$env/dynamic/private";

function getEnv(key: string): string {
	const val = env[key];
	if (!val) throw new Error(`Missing env var: ${key}`);
	return val;
}

export function getOAuth2Client() {
	return new OAuth2Client(
		getEnv("OIDC_CLIENT_ID"),
		getEnv("OIDC_CLIENT_SECRET"),
		`${getEnv("ORIGIN")}/auth/callback`
	);
}

export function getAuthorizeEndpoint() {
	return `${getEnv("OIDC_ISSUER")}/authorize`;
}

export function getTokenEndpoint() {
	return `${getEnv("OIDC_ISSUER")}/api/oidc/token`;
}

export function getUserinfoEndpoint() {
	return `${getEnv("OIDC_ISSUER")}/api/oidc/userinfo`;
}

export { CodeChallengeMethod };
