/**
 * Lightweight Loki logger for the SvelteKit dashboard.
 * Uses native fetch (fire-and-forget) so it never blocks requests.
 * Falls back to console if Loki is not configured.
 */
import { env } from "$env/dynamic/private";

const LOKI_URL = env.LOKI_URL;
const LOKI_ORG_ID = env.LOKI_ORG_ID;

function pushToLoki(
	level: string,
	message: string,
	extra: Record<string, string> = {}
) {
	if (!LOKI_URL) return;

	const labels: Record<string, string> = {
		service_name: "dashboard",
		environment: env.ENVIRONMENT || "production",
		level,
		...extra,
	};

	const tsNs = String(BigInt(Date.now()) * 1_000_000n);

	const payload = {
		streams: [{ stream: labels, values: [[tsNs, message]] }],
	};

	const headers: Record<string, string> = {
		"Content-Type": "application/json",
	};
	if (LOKI_ORG_ID) {
		headers["X-Scope-OrgID"] = LOKI_ORG_ID;
	}

	fetch(`${LOKI_URL.replace(/\/+$/, "")}/loki/api/v1/push`, {
		method: "POST",
		headers,
		body: JSON.stringify(payload),
	}).catch(() => {
		// Silently ignore – Loki outage must never affect the dashboard
	});
}

export const logger = {
	info(message: string, extra?: Record<string, string>) {
		console.log(`[INFO] ${message}`);
		pushToLoki("info", message, extra);
	},
	warn(message: string, extra?: Record<string, string>) {
		console.warn(`[WARN] ${message}`);
		pushToLoki("warn", message, extra);
	},
	error(message: string, extra?: Record<string, string>) {
		console.error(`[ERROR] ${message}`);
		pushToLoki("error", message, extra);
	},
};
