<script lang="ts">
	import { onMount } from "svelte";
	import type { ActiveHoursConfig, VacationMode, EmergencyContact, DirectForwarding, Contact } from "$lib/types";
	import { getActiveHours, getVacationMode, updateVacationMode, getEmergencyContact, updateEmergencyContact, getDirectForwarding, updateDirectForwarding, getContacts } from "$lib/api";
	import * as Card from "$lib/components/ui/card/index.js";
	import { Button } from "$lib/components/ui/button/index.js";
	import { Input } from "$lib/components/ui/input/index.js";
	import { Label } from "$lib/components/ui/label/index.js";
	import { Switch } from "$lib/components/ui/switch/index.js";
	import { Badge } from "$lib/components/ui/badge/index.js";
	import { Separator } from "$lib/components/ui/separator/index.js";
	import SunIcon from "@lucide/svelte/icons/sun";
	import MoonIcon from "@lucide/svelte/icons/moon";
	import ClockIcon from "@lucide/svelte/icons/clock";
	import PalmtreeIcon from "@lucide/svelte/icons/palmtree";
	import PhoneIcon from "@lucide/svelte/icons/phone";
	import CheckIcon from "@lucide/svelte/icons/check";
	import LoaderIcon from "@lucide/svelte/icons/loader";
	import AlertCircleIcon from "@lucide/svelte/icons/alert-circle";
	import ShieldAlertIcon from "@lucide/svelte/icons/shield-alert";
	import ForwardIcon from "@lucide/svelte/icons/forward";

	let config = $state<ActiveHoursConfig>({ day_start: 7, day_end: 20, twenty_four_seven: false });
	let vacation = $state<VacationMode>({ active: false, substitute_phone: "" });
	let emergencyContact = $state<EmergencyContact>({ contact_id: "", contact_name: "" });
	let directForwarding = $state<DirectForwarding>({ active: false, forward_phone: "", start_hour: 0, end_hour: 6 });
	let contacts = $state<Contact[]>([]);
	let loading = $state(true);
	let savingVacation = $state(false);
	let savingEmergency = $state(false);
	let savingForwarding = $state(false);
	let error = $state("");
	let success = $state("");

	async function load() {
		try {
			const [hours, vac, emergency, forwarding, allContacts] = await Promise.all([
				getActiveHours(),
				getVacationMode(),
				getEmergencyContact(),
				getDirectForwarding(),
				getContacts()
			]);
			config = hours;
			vacation = vac;
			emergencyContact = emergency;
			directForwarding = forwarding;
			contacts = Object.values(allContacts).flat().filter(c => !c.fallback);
			error = "";
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	onMount(load);

	async function saveVacation() {
		savingVacation = true;
		success = "";
		error = "";
		try {
			await updateVacationMode(vacation);
			success = "Urlaubsmodus gespeichert";
			setTimeout(() => { success = ""; }, 3000);
		} catch (e: any) {
			error = e.message;
		} finally {
			savingVacation = false;
		}
	}

	async function saveEmergency() {
		savingEmergency = true;
		success = "";
		error = "";
		try {
			await updateEmergencyContact(emergencyContact);
			success = "Notfallkontakt gespeichert";
			setTimeout(() => { success = ""; }, 3000);
		} catch (e: any) {
			error = e.message;
		} finally {
			savingEmergency = false;
		}
	}

	async function saveForwarding() {
		savingForwarding = true;
		success = "";
		error = "";
		try {
			await updateDirectForwarding(directForwarding);
			success = "Direkte Weiterleitung gespeichert";
			setTimeout(() => { success = ""; }, 3000);
		} catch (e: any) {
			error = e.message;
		} finally {
			savingForwarding = false;
		}
	}

	function handleEmergencySelect(e: Event) {
		const select = e.target as HTMLSelectElement;
		const contact = contacts.find(c => c.id === select.value);
		if (contact) {
			emergencyContact = { contact_id: contact.id, contact_name: contact.name };
		} else {
			emergencyContact = { contact_id: "", contact_name: "" };
		}
	}

	const currentMode = $derived((() => {
		const now = new Date();
		const hour = now.getHours();
		return (hour >= config.day_start && hour < config.day_end) ? "Tag" : "Nacht";
	})());
</script>

<div class="space-y-8 max-w-4xl mx-auto">
	<div>
		<h2 class="text-3xl font-bold tracking-tight">Einstellungen</h2>
		<p class="text-muted-foreground">Urlaubsmodus, Notfallkontakt und Weiterleitung konfigurieren</p>
	</div>

	{#if error}
		<div class="rounded-lg bg-red-50 border border-red-200 p-4 flex items-center gap-3">
			<AlertCircleIcon class="h-5 w-5 text-red-600 shrink-0" />
			<span class="text-red-800 text-sm">{error}</span>
		</div>
	{/if}
	{#if success}
		<div class="rounded-lg bg-green-50 border border-green-200 p-4 flex items-center gap-3">
			<CheckIcon class="h-5 w-5 text-green-600 shrink-0" />
			<span class="text-green-800 text-sm">{success}</span>
		</div>
	{/if}

	{#if loading}
		<div class="flex items-center justify-center py-12">
			<LoaderIcon class="h-8 w-8 animate-spin text-muted-foreground" />
		</div>
	{:else}
		<!-- Status Overview -->
		<div class="grid gap-4 md:grid-cols-3">
			<!-- Current Mode Card -->
			<Card.Root class={currentMode === "Nacht"
				? "border-indigo-200 bg-gradient-to-br from-indigo-50 to-purple-50"
				: "border-amber-200 bg-gradient-to-br from-amber-50 to-yellow-50"}>
				<Card.Content class="py-4">
					<div class="flex items-center gap-4">
						<div class={currentMode === "Nacht"
							? "p-3 rounded-full bg-indigo-100"
							: "p-3 rounded-full bg-amber-100"}>
							{#if currentMode === "Nacht"}
								<MoonIcon class="h-6 w-6 text-indigo-600" />
							{:else}
								<SunIcon class="h-6 w-6 text-amber-600" />
							{/if}
						</div>
						<div>
							<p class="text-sm font-medium text-muted-foreground">Aktueller Modus</p>
							<p class="text-2xl font-bold">{currentMode === "Tag" ? "Tagestarif" : "Nachttarif"}</p>
						</div>
					</div>
				</Card.Content>
			</Card.Root>

			<!-- Active Hours Card -->
			<Card.Root class="border-slate-200">
				<Card.Content class="py-4">
					<div class="flex items-center gap-4">
						<div class="p-3 rounded-full bg-slate-100">
							<ClockIcon class="h-6 w-6 text-slate-600" />
						</div>
						<div>
							<p class="text-sm font-medium text-muted-foreground">Tageszeit</p>
							<p class="text-2xl font-bold">{config.day_start}:00 - {config.day_end}:00</p>
						</div>
					</div>
				</Card.Content>
			</Card.Root>

			<!-- Vacation Status Card -->
			<Card.Root class={vacation.active
				? "border-orange-200 bg-gradient-to-br from-orange-50 to-amber-50"
				: "border-slate-200"}>
				<Card.Content class="py-4">
					<div class="flex items-center gap-4">
						<div class={vacation.active ? "p-3 rounded-full bg-orange-100" : "p-3 rounded-full bg-slate-100"}>
							<PalmtreeIcon class={vacation.active ? "h-6 w-6 text-orange-600" : "h-6 w-6 text-slate-600"} />
						</div>
						<div>
							<p class="text-sm font-medium text-muted-foreground">Urlaubsmodus</p>
							<p class="text-2xl font-bold">{vacation.active ? "Aktiv" : "Inaktiv"}</p>
						</div>
					</div>
				</Card.Content>
			</Card.Root>
		</div>

		<Separator />

		<div class="grid gap-6 lg:grid-cols-2">
			<!-- Vacation mode -->
			<Card.Root class={vacation.active ? "border-orange-200" : ""}>
				<Card.Header>
					<div class="flex items-center gap-3">
						<div class={vacation.active ? "p-2 rounded-lg bg-orange-100" : "p-2 rounded-lg bg-slate-100"}>
							<PalmtreeIcon class={vacation.active ? "h-5 w-5 text-orange-600" : "h-5 w-5 text-slate-600"} />
						</div>
						<div>
							<Card.Title>Urlaubsmodus</Card.Title>
							<Card.Description>Anrufe an Vertretung weiterleiten</Card.Description>
						</div>
					</div>
				</Card.Header>
				<Card.Content>
					<div class="grid gap-5">
						<div class="flex items-center justify-between p-4 rounded-lg bg-muted/50">
							<div class="flex items-center gap-3">
								<Switch id="vacation-toggle" bind:checked={vacation.active} />
								<Label for="vacation-toggle" class="font-medium cursor-pointer">
									{vacation.active ? "Urlaubsmodus aktiv" : "Urlaubsmodus deaktiviert"}
								</Label>
							</div>
							{#if vacation.active}
								<Badge class="bg-orange-100 text-orange-700 border-orange-200">Aktiv</Badge>
							{/if}
						</div>
						{#if vacation.active}
							<div class="grid gap-4 p-4 rounded-lg border border-orange-200 bg-orange-50/50">
								<div class="grid gap-2">
									<Label for="substitute_phone" class="flex items-center gap-2">
										<PhoneIcon class="h-4 w-4 text-muted-foreground" />
										Vertretungs-Telefon
									</Label>
									<Input id="substitute_phone" bind:value={vacation.substitute_phone} placeholder="+49 123 456789" class="bg-white" />
								</div>
							</div>
						{/if}
					</div>
				</Card.Content>
				<Card.Footer>
					<Button onclick={saveVacation} disabled={savingVacation} class="w-full">
						{#if savingVacation}
							<LoaderIcon class="h-4 w-4 mr-2 animate-spin" />
							Speichern...
						{:else}
							<CheckIcon class="h-4 w-4 mr-2" />
							Urlaubsmodus speichern
						{/if}
					</Button>
				</Card.Footer>
			</Card.Root>

			<!-- Emergency contact -->
			<Card.Root class={emergencyContact.contact_id ? "border-red-200" : ""}>
				<Card.Header>
					<div class="flex items-center gap-3">
						<div class={emergencyContact.contact_id ? "p-2 rounded-lg bg-red-100" : "p-2 rounded-lg bg-slate-100"}>
							<ShieldAlertIcon class={emergencyContact.contact_id ? "h-5 w-5 text-red-600" : "h-5 w-5 text-slate-600"} />
						</div>
						<div>
							<Card.Title>Notfallkontakt</Card.Title>
							<Card.Description>Kontakt für Notfälle außerhalb der Geschäftszeiten</Card.Description>
						</div>
					</div>
				</Card.Header>
				<Card.Content>
					<div class="grid gap-4">
						<div class="grid gap-2">
							<Label for="emergency-contact">Kontakt auswählen</Label>
							<select
								id="emergency-contact"
								class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
								value={emergencyContact.contact_id}
								onchange={handleEmergencySelect}
							>
								<option value="">-- Kein Notfallkontakt --</option>
								{#each contacts as contact}
									<option value={contact.id}>{contact.name}</option>
								{/each}
							</select>
						</div>
						{#if emergencyContact.contact_id}
							<div class="p-3 rounded-lg bg-red-50 border border-red-200">
								<p class="text-sm text-red-700">
									<span class="font-medium">{emergencyContact.contact_name}</span> wird im Zweifelsfall kontaktiert.
								</p>
							</div>
						{/if}
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

		</div>
	{/if}
</div>
