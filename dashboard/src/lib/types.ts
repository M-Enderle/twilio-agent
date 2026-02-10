export interface Contact {
	id: string;
	name: string;
	phone: string;
	address: string;
	zipcode: string | number;
	fallback: boolean;
}

export interface ActiveHoursConfig {
	day_start: number;
	day_end: number;
	twenty_four_seven: boolean;
}

export interface VacationMode {
	active: boolean;
	substitute_phone: string;
	note: string;
}

export interface SystemStatus {
	total_contacts: number;
	vacation_active: boolean;
	active_hours: ActiveHoursConfig;
	categories: Record<string, number>;
}

export type Category = "locksmith" | "towing";
