export type ServiceId = "schluessel-allgaeu" | "notdienst-schluessel" | "notdienst-abschlepp";

export interface ServiceDefinition {
	id: ServiceId;
	label: string;
	shortLabel: string;
	icon: "key" | "truck";
}

export const SERVICES: ServiceDefinition[] = [
	{ id: "schluessel-allgaeu", label: "Schlüsseldienst Allgäu", shortLabel: "SD Allgäu", icon: "key" },
	{ id: "notdienst-schluessel", label: "Notdienststation Schlüsseldienst", shortLabel: "NDS Schlüssel", icon: "key" },
	{ id: "notdienst-abschlepp", label: "Notdienststation Abschleppdienst", shortLabel: "NDS Abschlepp", icon: "truck" },
];

export interface StandortKontakt {
	name: string;
	phone: string;
	position: number;
}

export interface Standort {
	id: string;
	name: string;
	address?: string;
	latitude?: number;
	longitude?: number;
	contacts: StandortKontakt[];
}

export interface ActiveHoursConfig {
	day_start: number;
	day_end: number;
	twenty_four_seven: boolean;
}

export interface PhoneNumber {
	phone_number: string;
}

export interface EmergencyContact {
	name: string;
	phone: string;
}

export interface DirectForwarding {
	active: boolean;
	forward_phone: string;
	start_hour: number;
	end_hour: number;
}

export interface SystemStatus {
	total_contacts: number;
	active_hours: ActiveHoursConfig;
	categories: Record<string, number>;
}

export interface PricingTier {
	minutes: number;
	dayPrice: number;
	nightPrice: number;
}

export interface ServicePricing {
	tiers: PricingTier[];
	fallbackDayPrice: number;
	fallbackNightPrice: number;
}

export interface CallSummary {
	number: string;
	timestamp: string;
	phone: string;
	start_time: string;
	intent: string;
	live: boolean;
	location: string | Record<string, unknown>;
	latitude?: number;
	longitude?: number;
	provider: string;
	price: string;
	hangup_reason: string;
	transferred_to: string;
	service?: ServiceId;
}

export interface CallMessage {
	role: string;
	role_class: string;
	content: string;
	model?: string;
}

export interface RecordingInfo {
	recording_type: string;
	content_type: string;
	metadata: Record<string, any>;
	number: string;
	timestamp: string;
}

export interface CallDetail {
	info: Record<string, any>;
	messages: CallMessage[];
	recordings: Record<string, RecordingInfo>;
}

export interface Announcements {
	// Begrüßung
	greeting: string;
	// Adresse erfassen
	address_request: string;
	address_processing: string;
	address_confirm: string;
	address_confirm_prompt: string;
	// PLZ Fallback
	zipcode_request: string;
	plz_invalid_format: string;
	plz_outside_area: string;
	plz_not_found: string;
	// SMS Standort
	sms_offer: string;
	sms_sent_confirmation: string;
	// Preisangebot
	price_offer: string;
	price_offer_prompt: string;
	connection_declined: string;
	connection_timeout: string;
	// Transfer
	transfer_message: string;
}

export interface TransferSettings {
	ring_timeout: number;
}
