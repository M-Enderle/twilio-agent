import type { Standort, ActiveHoursConfig, PhoneNumber, EmergencyContact, DirectForwarding, SystemStatus, ServicePricing, Announcements, TransferSettings, ServiceId, CallSummary, CallDetail } from "./types";

function getApiBase(): string {
	if (typeof window === "undefined") {
		return "http://localhost:8000/api/dashboard";
	}
	if (window.__API_URL__) {
		return window.__API_URL__;
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
	if (res.status === 401) {
		window.location.href = "/auth/logout";
		throw new Error("Nicht autorisiert. Bitte erneut anmelden.");
	}
	if (!res.ok) {
		const detail = await res.text();
		console.error(`API error ${res.status}:`, detail);
		if (res.status === 403) {
			throw new Error("Zugriff verweigert.");
		} else if (res.status === 404) {
			throw new Error("Ressource nicht gefunden.");
		} else if (res.status >= 500) {
			throw new Error("Serverfehler. Bitte später erneut versuchen.");
		} else {
			throw new Error(`Anfrage fehlgeschlagen (${res.status}).`);
		}
	}
	return res.json();
}

// Standorte (Locations)
export function getStandorte(serviceId: ServiceId): Promise<Standort[]> {
	return request(`/services/${serviceId}/locations`);
}

export function createStandort(serviceId: ServiceId, data: Omit<Standort, "id">): Promise<Standort> {
	return request(`/services/${serviceId}/locations`, {
		method: "POST",
		body: JSON.stringify(data),
	});
}

export function updateStandort(serviceId: ServiceId, id: string, data: Partial<Standort>): Promise<Standort> {
	return request(`/services/${serviceId}/locations/${id}`, {
		method: "PUT",
		body: JSON.stringify(data),
	});
}

export function deleteStandort(serviceId: ServiceId, id: string): Promise<void> {
	return request(`/services/${serviceId}/locations/${id}`, { method: "DELETE" });
}

export function reorderStandorte(serviceId: ServiceId, ids: string[]): Promise<Standort[]> {
	return request(`/services/${serviceId}/locations/reorder`, {
		method: "PUT",
		body: JSON.stringify({ ids }),
	});
}

// Phone number
export function getPhoneNumber(serviceId: ServiceId): Promise<PhoneNumber> {
	return request(`/services/${serviceId}/settings/phone-number`);
}

export function updatePhoneNumber(serviceId: ServiceId, config: PhoneNumber): Promise<PhoneNumber> {
	return request(`/services/${serviceId}/settings/phone-number`, {
		method: "PUT",
		body: JSON.stringify(config),
	});
}

// Settings
export function getActiveHours(serviceId: ServiceId): Promise<ActiveHoursConfig> {
	return request(`/services/${serviceId}/settings/active-hours`);
}

export function updateActiveHours(serviceId: ServiceId, config: ActiveHoursConfig): Promise<ActiveHoursConfig> {
	return request(`/services/${serviceId}/settings/active-hours`, {
		method: "PUT",
		body: JSON.stringify(config),
	});
}

// Emergency contact
export function getEmergencyContact(serviceId: ServiceId): Promise<EmergencyContact> {
	return request(`/services/${serviceId}/settings/emergency-contact`);
}

export function updateEmergencyContact(serviceId: ServiceId, config: EmergencyContact): Promise<EmergencyContact> {
	return request(`/services/${serviceId}/settings/emergency-contact`, {
		method: "PUT",
		body: JSON.stringify(config),
	});
}

// Direct forwarding
export function getDirectForwarding(serviceId: ServiceId): Promise<DirectForwarding> {
	return request(`/services/${serviceId}/settings/direct-forwarding`);
}

export function updateDirectForwarding(serviceId: ServiceId, config: DirectForwarding): Promise<DirectForwarding> {
	return request(`/services/${serviceId}/settings/direct-forwarding`, {
		method: "PUT",
		body: JSON.stringify(config),
	});
}

export function getTransferSettings(serviceId: ServiceId): Promise<TransferSettings> {
	return request(`/services/${serviceId}/settings/transfer`);
}

export function updateTransferSettings(serviceId: ServiceId, config: TransferSettings): Promise<TransferSettings> {
	return request(`/services/${serviceId}/settings/transfer`, {
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
export function getPricing(serviceId: ServiceId): Promise<ServicePricing> {
	return request(`/services/${serviceId}/settings/pricing`);
}

export function updatePricing(serviceId: ServiceId, config: ServicePricing): Promise<ServicePricing> {
	return request(`/services/${serviceId}/settings/pricing`, {
		method: "PUT",
		body: JSON.stringify(config),
	});
}

// Announcements
export function getAnnouncements(serviceId: ServiceId): Promise<Announcements> {
	return request(`/services/${serviceId}/settings/announcements`);
}

export function updateAnnouncements(serviceId: ServiceId, config: Announcements): Promise<Announcements> {
	return request(`/services/${serviceId}/settings/announcements`, {
		method: "PUT",
		body: JSON.stringify(config),
	});
}

// Calls
export function getCalls(serviceId?: ServiceId): Promise<{ calls: CallSummary[]; total: number }> {
	const params = serviceId ? `?service=${serviceId}` : "";
	return request(`/calls${params}`);
}

export function getCallDetail(number: string, timestamp: string): Promise<CallDetail> {
	return request(`/calls/${number}/${timestamp}`);
}

export async function fetchRecordingBlob(
	number: string,
	timestamp: string,
	recordingType: string
): Promise<string> {
	const headers: Record<string, string> = {};
	if (_token) {
		headers["Authorization"] = `Bearer ${_token}`;
	}
	const res = await fetch(
		`${getApiBase()}/calls/${number}/${timestamp}/recording/${recordingType}`,
		{ headers }
	);
	if (res.status === 401) {
		window.location.href = "/auth/logout";
		throw new Error("Session expired");
	}
	if (!res.ok) {
		throw new Error(`Recording fetch failed: ${res.status}`);
	}
	const blob = await res.blob();
	return URL.createObjectURL(blob);
}

export function getRecordingUrl(
	number: string,
	timestamp: string,
	recordingType: string
): string {
	// Return direct URL to recording endpoint (preserves HTTP headers for duration)
	return `${getApiBase()}/calls/${number}/${timestamp}/recording/${recordingType}`;
}

// Service Territories (driving time grid cache)
export interface TerritoryData {
	grid: Array<{ lat: number; lng: number; contactIndex: number }>;
	locations_hash: string;
	computed_at: string | null;
	is_partial?: boolean;
	total_points?: number;
	bounds?: { minLat: number; maxLat: number; minLng: number; maxLng: number };
}

export function getTerritories(serviceId: ServiceId): Promise<TerritoryData> {
	return request(`/services/${serviceId}/territories`);
}

export function saveTerritories(serviceId: ServiceId, data: TerritoryData): Promise<{ status: string }> {
	return request(`/services/${serviceId}/territories`, {
		method: "POST",
		body: JSON.stringify(data),
	});
}
