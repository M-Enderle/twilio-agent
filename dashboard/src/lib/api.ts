import type { Contact, ActiveHoursConfig, VacationMode, EmergencyContact, DirectForwarding, SystemStatus, Category, PricingConfig } from "./types";

function getApiBase(): string {
	if (typeof window === "undefined") {
		return "http://localhost:8000/api/dashboard";
	}
	if ((window as any).__API_URL__) {
		return (window as any).__API_URL__;
	}
	// Use the same hostname as the current page, but port 8000
	return `${window.location.protocol}//${window.location.hostname}:8000/api/dashboard`;
}

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
	const res = await fetch(`${getApiBase()}${path}`, {
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

// Emergency contact
export function getEmergencyContact(): Promise<EmergencyContact> {
	return request("/settings/emergency-contact");
}

export function updateEmergencyContact(config: EmergencyContact): Promise<EmergencyContact> {
	return request("/settings/emergency-contact", {
		method: "PUT",
		body: JSON.stringify(config),
	});
}

// Direct forwarding
export function getDirectForwarding(): Promise<DirectForwarding> {
	return request("/settings/direct-forwarding");
}

export function updateDirectForwarding(config: DirectForwarding): Promise<DirectForwarding> {
	return request("/settings/direct-forwarding", {
		method: "PUT",
		body: JSON.stringify(config),
	});
}

// Status
export function getStatus(): Promise<SystemStatus> {
	return request("/status");
}

// Geocoding
export interface GeocodeResult {
	latitude: number;
	longitude: number;
	formatted_address: string;
}

export function geocodeAddress(address: string): Promise<GeocodeResult> {
	return request("/geocode", {
		method: "POST",
		body: JSON.stringify({ address }),
	});
}

// Pricing
export function getPricing(): Promise<PricingConfig> {
	return request("/settings/pricing");
}

export function updatePricing(config: PricingConfig): Promise<PricingConfig> {
	return request("/settings/pricing", {
		method: "PUT",
		body: JSON.stringify(config),
	});
}

// Service Territories (driving time grid cache)
export interface TerritoryData {
	grid: Array<{ lat: number; lng: number; contactIndex: number }>;
	contacts_hash: string;
	computed_at: string | null;
	is_partial?: boolean;
	total_points?: number;
}

export function getTerritories(category: Category): Promise<TerritoryData> {
	return request(`/territories/${category}`);
}

export function saveTerritories(category: Category, data: TerritoryData): Promise<{ status: string }> {
	return request(`/territories/${category}`, {
		method: "POST",
		body: JSON.stringify(data),
	});
}
