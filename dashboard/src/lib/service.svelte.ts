import type { ServiceId } from "./types";
import { SERVICES } from "./types";

const STORAGE_KEY = "notdienststation:selected-service";

function loadFromStorage(): ServiceId {
	if (typeof window === "undefined") return SERVICES[0].id;
	const stored = localStorage.getItem(STORAGE_KEY);
	if (stored && SERVICES.some((s) => s.id === stored)) {
		return stored as ServiceId;
	}
	return SERVICES[0].id;
}

let selectedService = $state<ServiceId>(loadFromStorage());
let version = $state(0);

export function getSelectedService(): ServiceId {
	return selectedService;
}

export function setSelectedService(id: ServiceId) {
	selectedService = id;
	version++;
	if (typeof window !== "undefined") {
		localStorage.setItem(STORAGE_KEY, id);
	}
}

export function getServiceVersion(): number {
	return version;
}
