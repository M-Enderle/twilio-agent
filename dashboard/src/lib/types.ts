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
	zipcode?: string | number;
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
	location: string;
	provider: string;
	price: string;
	hangup_reason: string;
	transferred_to: string;
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
	greeting: string;
	intent_prompt: string;
	intent_not_understood: string;
	intent_failed: string;
	address_request: string;
	address_processing: string;
	address_confirm: string;
	address_confirm_prompt: string;
	zipcode_request: string;
	sms_offer: string;
	sms_confirm_prompt: string;
	sms_declined: string;
	sms_sent: string;
	sms_text: string;
	price_quote: string;
	yes_no_prompt: string;
	transfer_message: string;
	goodbye: string;
	all_busy: string;
	no_input: string;
	outbound_greeting: string;
	outbound_yes_no: string;
	driver_sms: string;
}
