export interface Contact {
	id: string;
	name: string;
	phone: string;
	address: string;
	zipcode: string | number;
	fallback: boolean;
	latitude?: number;
	longitude?: number;
	fallbacks_json?: string;
}

export interface FallbackContact {
	id: string;
	name: string;
	phone: string;
}

export interface ContactWithCoords extends Contact {
	fallbacks?: FallbackContact[];
}

export interface ActiveHoursConfig {
	day_start: number;
	day_end: number;
	twenty_four_seven: boolean;
}

export interface VacationMode {
	active: boolean;
	substitute_phone: string;
}

export interface EmergencyContact {
	contact_id: string;
	contact_name: string;
}

export interface DirectForwarding {
	active: boolean;
	forward_phone: string;
	start_hour: number;
	end_hour: number;
}

export interface SystemStatus {
	total_contacts: number;
	vacation_active: boolean;
	active_hours: ActiveHoursConfig;
	categories: Record<string, number>;
}

export type Category = "locksmith" | "towing";

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

export interface PricingConfig {
	locksmith: ServicePricing;
	towing: ServicePricing;
}
