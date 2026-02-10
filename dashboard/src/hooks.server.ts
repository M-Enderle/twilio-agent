import { redirect, type Handle } from "@sveltejs/kit";
import { sequence } from "@sveltejs/kit/hooks";
import { handle as authHandle } from "./auth";

const guardHandle: Handle = async ({ event, resolve }) => {
	const { pathname } = event.url;

	// Allow auth routes and login page through
	if (pathname.startsWith("/auth") || pathname === "/login") {
		return resolve(event);
	}

	const session = await event.locals.auth();
	if (!session) {
		throw redirect(303, "/login");
	}

	return resolve(event);
};

export const handle = sequence(authHandle, guardHandle);
