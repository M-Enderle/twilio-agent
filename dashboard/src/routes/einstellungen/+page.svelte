<script lang="ts">
	import type { ActiveHoursConfig, PhoneNumber, EmergencyContact, DirectForwarding, TransferSettings } from "$lib/types";
	import { SERVICES } from "$lib/types";
	import { getActiveHours, getPhoneNumber, updatePhoneNumber, getEmergencyContact, updateEmergencyContact, getDirectForwarding, updateDirectForwarding, getTransferSettings, updateTransferSettings } from "$lib/api";
	import { getSelectedService, getServiceVersion } from "$lib/service.svelte";
	import * as Card from "$lib/components/ui/card/index.js";
	import { Button } from "$lib/components/ui/button/index.js";
	import { Input } from "$lib/components/ui/input/index.js";
	import { Label } from "$lib/components/ui/label/index.js";
	import { Switch } from "$lib/components/ui/switch/index.js";
	import { Badge } from "$lib/components/ui/badge/index.js";
	import AlertBanner from "$lib/components/AlertBanner.svelte";
	import ClockIcon from "@lucide/svelte/icons/clock";
	import PhoneIcon from "@lucide/svelte/icons/phone";
	import CheckIcon from "@lucide/svelte/icons/check";
	import LoaderIcon from "@lucide/svelte/icons/loader";
	import ShieldAlertIcon from "@lucide/svelte/icons/shield-alert";
	import ForwardIcon from "@lucide/svelte/icons/forward";
	import TimerIcon from "@lucide/svelte/icons/timer";
	import { isValidE164 } from "$lib/utils";

	let config = $state<ActiveHoursConfig>({ day_start: 7, day_end: 20, twenty_four_seven: false });
	let phoneNumber = $state<PhoneNumber>({ phone_number: "" });
	let emergencyContact = $state<EmergencyContact>({ name: "", phone: "" });
	let directForwarding = $state<DirectForwarding>({ active: false, forward_phone: "", start_hour: 0, end_hour: 6 });
	let transferSettings = $state<TransferSettings>({ ring_timeout: 15 });
	let loading = $state(true);
	let savingPhone = $state(false);
	let savingEmergency = $state(false);
	let savingForwarding = $state(false);
	let savingTransfer = $state(false);
	let error = $state("");
	let success = $state("");

	const serviceId = $derived(getSelectedService());
	const serviceLabel = $derived(SERVICES.find((s) => s.id === serviceId)?.label ?? serviceId);

	async function load() {
		loading = true;
		try {
			const [hours, phone, emergency, forwarding, transfer] = await Promise.all([
				getActiveHours(serviceId),
				getPhoneNumber(serviceId),
				getEmergencyContact(serviceId),
				getDirectForwarding(serviceId),
				getTransferSettings(serviceId)
			]);
			config = hours;
			phoneNumber = phone;
			emergencyContact = emergency;
			directForwarding = forwarding;
			transferSettings = transfer;
			error = "";
		} catch (e) {
			error = e instanceof Error ? e.message : "Ein unbekannter Fehler ist aufgetreten.";
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		serviceId;
		getServiceVersion();
		load();
	});

	async function savePhone() {
		if (phoneNumber.phone_number && !isValidE164(phoneNumber.phone_number)) {
			error = "Ungültiges Telefonnummernformat. Bitte im Format +49... eingeben.";
			return;
		}
		savingPhone = true;
		success = "";
		error = "";
		try {
			await updatePhoneNumber(serviceId, phoneNumber);
			success = "Telefonnummer gespeichert";
			setTimeout(() => { success = ""; }, 3000);
		} catch (e) {
			error = e instanceof Error ? e.message : "Speichern fehlgeschlagen.";
		} finally {
			savingPhone = false;
		}
	}

	async function saveEmergency() {
		savingEmergency = true;
		success = "";
		error = "";
		try {
			await updateEmergencyContact(serviceId, emergencyContact);
			success = "Notfallkontakt gespeichert";
			setTimeout(() => { success = ""; }, 3000);
		} catch (e) {
			error = e instanceof Error ? e.message : "Speichern fehlgeschlagen.";
		} finally {
			savingEmergency = false;
		}
	}

	async function saveForwarding() {
		savingForwarding = true;
		success = "";
		error = "";
		try {
			await updateDirectForwarding(serviceId, directForwarding);
			success = "Direkte Weiterleitung gespeichert";
			setTimeout(() => { success = ""; }, 3000);
		} catch (e) {
			error = e instanceof Error ? e.message : "Speichern fehlgeschlagen.";
		} finally {
			savingForwarding = false;
		}
	}

	async function saveTransfer() {
		savingTransfer = true;
		success = "";
		error = "";
		try {
			await updateTransferSettings(serviceId, transferSettings);
			success = "Weiterleitungseinstellungen gespeichert";
			setTimeout(() => { success = ""; }, 3000);
		} catch (e) {
			error = e instanceof Error ? e.message : "Speichern fehlgeschlagen.";
		} finally {
			savingTransfer = false;
		}
	}


</script>

<div class="space-y-8 max-w-4xl mx-auto">
	<div>
		<h2 class="text-3xl font-bold tracking-tight">Einstellungen</h2>
		<p class="text-muted-foreground">Telefonnummer, Notfallkontakt und Weiterleitung konfigurieren ({serviceLabel})</p>
	</div>

	<AlertBanner type="error" message={error} />
	<AlertBanner type="success" message={success} />

	{#if loading}
		<div class="flex items-center justify-center py-12">
			<LoaderIcon class="h-8 w-8 animate-spin text-muted-foreground" />
		</div>
	{:else}
		<div class="grid gap-6 lg:grid-cols-2">
			<!-- Phone number -->
			<Card.Root>
				<Card.Header>
					<div class="flex items-center gap-3">
						<div class="p-2 rounded-lg bg-slate-100">
							<PhoneIcon class="h-5 w-5 text-slate-600" />
						</div>
						<div>
							<Card.Title>Telefonnummer</Card.Title>
							<Card.Description>Twilio-Nummer unter der der Agent erreichbar ist</Card.Description>
						</div>
					</div>
				</Card.Header>
				<Card.Content>
					<div class="grid gap-2">
						<Label for="phone_number" class="flex items-center gap-2">
							<PhoneIcon class="h-4 w-4 text-muted-foreground" />
							Telefonnummer
						</Label>
						<Input id="phone_number" bind:value={phoneNumber.phone_number} placeholder="+49 123 456789" />
					</div>
				</Card.Content>
				<Card.Footer>
					<Button onclick={savePhone} disabled={savingPhone} class="w-full">
						{#if savingPhone}
							<LoaderIcon class="h-4 w-4 mr-2 animate-spin" />
							Speichern...
						{:else}
							<CheckIcon class="h-4 w-4 mr-2" />
							Telefonnummer speichern
						{/if}
					</Button>
				</Card.Footer>
			</Card.Root>

			<!-- Emergency contact -->
			<Card.Root class={emergencyContact.name && emergencyContact.phone ? "border-red-200" : ""}>
				<Card.Header>
					<div class="flex items-center gap-3">
						<div class={emergencyContact.name && emergencyContact.phone ? "p-2 rounded-lg bg-red-100" : "p-2 rounded-lg bg-slate-100"}>
							<ShieldAlertIcon class={emergencyContact.name && emergencyContact.phone ? "h-5 w-5 text-red-600" : "h-5 w-5 text-slate-600"} />
						</div>
						<div>
							<Card.Title>Notfallkontakt</Card.Title>
							<Card.Description>Wer soll kontaktiert werden wenn kein Standort bestimmt werden kann</Card.Description>
						</div>
					</div>
				</Card.Header>
				<Card.Content>
					<div class="grid gap-4">
						<div class="grid gap-2">
							<Label for="emergency-name">Name</Label>
							<Input id="emergency-name" bind:value={emergencyContact.name} placeholder="z.B. Max Mustermann" />
						</div>
						<div class="grid gap-2">
							<Label for="emergency-phone">Telefonnummer</Label>
							<Input id="emergency-phone" bind:value={emergencyContact.phone} placeholder="+49 123 456789" />
						</div>
					</div>
				</Card.Content>
				<Card.Footer>
					<Button onclick={saveEmergency} disabled={savingEmergency} class="w-full">
						{#if savingEmergency}
							<LoaderIcon class="h-4 w-4 mr-2 animate-spin" />
							Speichern...
						{:else}
							<CheckIcon class="h-4 w-4 mr-2" />
							Notfallkontakt speichern
						{/if}
					</Button>
				</Card.Footer>
			</Card.Root>

			<!-- Direct forwarding -->
			<Card.Root class={directForwarding.active ? "border-blue-200" : ""}>
				<Card.Header>
					<div class="flex items-center gap-3">
						<div class={directForwarding.active ? "p-2 rounded-lg bg-blue-100" : "p-2 rounded-lg bg-slate-100"}>
							<ForwardIcon class={directForwarding.active ? "h-5 w-5 text-blue-600" : "h-5 w-5 text-slate-600"} />
						</div>
						<div>
							<Card.Title>Direkte Weiterleitung</Card.Title>
							<Card.Description>Anrufe in einem Zeitfenster direkt weiterleiten</Card.Description>
						</div>
					</div>
				</Card.Header>
				<Card.Content>
					<div class="grid gap-5">
						<div class="flex items-center justify-between p-4 rounded-lg bg-muted/50">
							<div class="flex items-center gap-3">
								<Switch id="forwarding-toggle" bind:checked={directForwarding.active} />
								<Label for="forwarding-toggle" class="font-medium cursor-pointer">
									{directForwarding.active ? "Weiterleitung aktiv" : "Weiterleitung deaktiviert"}
								</Label>
							</div>
							{#if directForwarding.active}
								<Badge class="bg-blue-100 text-blue-700 border-blue-200">Aktiv</Badge>
							{/if}
						</div>
						{#if directForwarding.active}
							<div class="grid gap-4 p-4 rounded-lg border border-blue-200 bg-blue-50/50">
								<div class="grid gap-2">
									<Label for="forward_phone" class="flex items-center gap-2">
										<PhoneIcon class="h-4 w-4 text-muted-foreground" />
										Weiterleitungs-Telefon
									</Label>
									<Input id="forward_phone" bind:value={directForwarding.forward_phone} placeholder="+49 123 456789" class="bg-white" />
								</div>
								<div class="grid grid-cols-2 gap-4">
									<div class="grid gap-2">
										<Label for="start_hour" class="flex items-center gap-2">
											<ClockIcon class="h-4 w-4 text-muted-foreground" />
											Von
										</Label>
										<select
											id="start_hour"
											class="flex h-10 w-full rounded-md border border-input bg-white px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
											value={directForwarding.start_hour}
											onchange={(e) => directForwarding.start_hour = parseFloat((e.target as HTMLSelectElement).value)}
										>
											{#each Array.from({ length: 48 }, (_, i) => i * 0.5) as time}
												<option value={time}>{Math.floor(time)}:{time % 1 === 0 ? '00' : '30'} Uhr</option>
											{/each}
										</select>
									</div>
									<div class="grid gap-2">
										<Label for="end_hour" class="flex items-center gap-2">
											<ClockIcon class="h-4 w-4 text-muted-foreground" />
											Bis
										</Label>
										<select
											id="end_hour"
											class="flex h-10 w-full rounded-md border border-input bg-white px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
											value={directForwarding.end_hour}
											onchange={(e) => directForwarding.end_hour = parseFloat((e.target as HTMLSelectElement).value)}
										>
											{#each Array.from({ length: 49 }, (_, i) => i * 0.5) as time}
												<option value={time}>{Math.floor(time)}:{time % 1 === 0 ? '00' : '30'} Uhr</option>
											{/each}
										</select>
									</div>
								</div>
							</div>
						{/if}
					</div>
				</Card.Content>
				<Card.Footer>
					<Button onclick={saveForwarding} disabled={savingForwarding} class="w-full">
						{#if savingForwarding}
							<LoaderIcon class="h-4 w-4 mr-2 animate-spin" />
							Speichern...
						{:else}
							<CheckIcon class="h-4 w-4 mr-2" />
							Weiterleitung speichern
						{/if}
					</Button>
				</Card.Footer>
			</Card.Root>

			<!-- Transfer Settings -->
			<Card.Root>
				<Card.Header>
					<div class="flex items-center gap-3">
						<div class="p-2 rounded-lg bg-slate-100">
							<TimerIcon class="h-5 w-5 text-slate-600" />
						</div>
						<div>
							<Card.Title>Weiterleitungseinstellungen</Card.Title>
							<Card.Description>Klingeldauer bei Anrufweiterleitung</Card.Description>
						</div>
					</div>
				</Card.Header>
				<Card.Content>
					<div class="grid gap-2">
						<Label for="ring_timeout" class="flex items-center gap-2">
							<TimerIcon class="h-4 w-4 text-muted-foreground" />
							Klingeldauer (Sekunden)
						</Label>
						<Input
							id="ring_timeout"
							type="number"
							min="5"
							max="60"
							bind:value={transferSettings.ring_timeout}
							placeholder="15"
						/>
						<p class="text-xs text-muted-foreground">
							Wie lange soll der Kontakt klingeln bevor der nächste versucht wird? (5-60 Sekunden)
						</p>
					</div>
				</Card.Content>
				<Card.Footer>
					<Button onclick={saveTransfer} disabled={savingTransfer} class="w-full">
						{#if savingTransfer}
							<LoaderIcon class="h-4 w-4 mr-2 animate-spin" />
							Speichern...
						{:else}
							<CheckIcon class="h-4 w-4 mr-2" />
							Einstellungen speichern
						{/if}
					</Button>
				</Card.Footer>
			</Card.Root>

		</div>
	{/if}
</div>
