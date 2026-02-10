import type { Contact, ActiveHoursConfig, VacationMode, SystemStatus, Category } from "./types";

const API_BASE = (typeof window !== "undefined" && (window as any).__API_URL__)
	? (window as any).__API_URL__
	: "http://localhost:8000/api/dashboard";

let _token: string | null = null;

export function setToken(token: string | null) {
	_token = token;
}

export function getToken(): string | null {
	return _token;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
	const headers: Record<string, string> = { "Content-Type": "application/json" };
	if (_token) {
		headers["Authorization"] = `Bearer ${_token}`;
	}
	const res = await fetch(`${API_BASE}${path}`, {
		headers,
		...options,
	});
	if (!res.ok) {
		const detail = await res.text();
		throw new Error(`API error ${res.status}: ${detail}`);
	}
	return res.json();
}

// Contacts
export function getContacts(): Promise<Record<Category, Contact[]>> {
	return request("/contacts");
}

export function createContact(category: Category, data: Omit<Contact, "id">): Promise<Contact> {
	return request(`/contacts/${category}`, {
		method: "POST",
		body: JSON.stringify(data),
	});
}

export function updateContact(category: Category, id: string, data: Partial<Contact>): Promise<Contact> {
	return request(`/contacts/${category}/${id}`, {
		method: "PUT",
		body: JSON.stringify(data),
	});
}

export function deleteContact(category: Category, id: string): Promise<void> {
	return request(`/contacts/${category}/${id}`, { method: "DELETE" });
}

export function reorderContacts(category: Category, ids: string[]): Promise<Contact[]> {
	return request(`/contacts/${category}/reorder`, {
		method: "PUT",
		body: JSON.stringify({ ids }),
	});
}

// Vacation mode
export function getVacationMode(): Promise<VacationMode> {
	return request("/settings/vacation");
}

export function updateVacationMode(config: VacationMode): Promise<VacationMode> {
	return request("/settings/vacation", {
		method: "PUT",
		body: JSON.stringify(config),
	});
}

// Settings
export function getActiveHours(): Promise<ActiveHoursConfig> {
	return request("/settings/active-hours");
}

export function updateActiveHours(config: ActiveHoursConfig): Promise<ActiveHoursConfig> {
	return request("/settings/active-hours", {
		method: "PUT",
		body: JSON.stringify(config),
	});
}

// Status
export function getStatus(): Promise<SystemStatus> {
	return request("/status");
}
