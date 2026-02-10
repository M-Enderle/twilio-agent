import { SvelteKitAuth } from "@auth/sveltekit";
import type { Provider } from "@auth/sveltekit/providers";
import { env } from "$env/dynamic/private";

const PocketID: Provider = {
	id: "pocketid",
	name: "PocketID",
	type: "oidc",
	issuer: env.POCKETID_ISSUER,
	clientId: env.POCKETID_CLIENT_ID,
	clientSecret: env.POCKETID_CLIENT_SECRET,
	authorization: { params: { scope: "openid profile email" } },
};

export const { handle, signIn, signOut } = SvelteKitAuth({
	providers: [PocketID],
	callbacks: {
		async jwt({ token, account }) {
			if (account) {
				token.accessToken = account.access_token;
			}
			return token;
		},
		async session({ session, token }) {
			(session as any).accessToken = token.accessToken;
			return session;
		},
	},
	trustHost: true,
});
