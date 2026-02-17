import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
	return twMerge(clsx(inputs));
}

export type WithElementRef<T, El extends HTMLElement = HTMLElement> = T & {
	ref?: El | null;
};

export type WithoutChild<T> = Omit<T, "child">;
export type WithoutChildren<T> = Omit<T, "children">;
export type WithoutChildrenOrChild<T> = Omit<T, "children" | "child">;

/**
 * Format a phone number for display: replace leading 00 with +
 */
export function formatPhone(value: string): string {
	if (!value) return "";
	return value.replace(/^00/, "+");
}

/**
 * Format a date string to German locale with full date and time
 */
export function formatDateTime(value: string): string {
	if (!value) return "";
	try {
		return new Date(value).toLocaleString("de-DE", {
			day: "2-digit",
			month: "2-digit",
			year: "numeric",
			hour: "2-digit",
			minute: "2-digit",
		});
	} catch {
		return value;
	}
}

/**
 * Format a date string to German locale with short date (no year)
 */
export function formatDateTimeShort(value: string): string {
	if (!value) return "";
	try {
		return new Date(value).toLocaleString("de-DE", {
			day: "2-digit",
			month: "2-digit",
			hour: "2-digit",
			minute: "2-digit",
		});
	} catch {
		return value;
	}
}

/**
 * Validate E.164 phone number format (e.g. +491234567890)
 */
export function isValidE164(phone: string): boolean {
	return /^\+[1-9]\d{6,14}$/.test(phone.replace(/\s/g, ""));
}
