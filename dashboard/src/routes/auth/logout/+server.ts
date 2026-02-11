import { redirect } from "@sveltejs/kit";

export async function GET({ cookies }) {
	cookies.delete("session", { path: "/" });
	throw redirect(302, "/auth/login");
}
