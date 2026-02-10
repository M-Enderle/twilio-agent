// See https://svelte.dev/docs/kit/types#app.d.ts
// for information about these interfaces
import type { Session } from "@auth/core/types";

declare module "@auth/core/types" {
	interface Session {
		accessToken?: string;
	}
}

declare module "@auth/core/jwt" {
	interface JWT {
		accessToken?: string;
	}
}

declare global {
	namespace App {
		// interface Error {}
		// interface Locals {}
		// interface PageData {}
		// interface PageState {}
		// interface Platform {}
	}
}

export {};
