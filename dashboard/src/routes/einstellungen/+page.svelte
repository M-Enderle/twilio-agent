<script lang="ts">
	import { onMount } from "svelte";
	import type { ActiveHoursConfig, VacationMode } from "$lib/types";
	import { getActiveHours, updateActiveHours, getVacationMode, updateVacationMode } from "$lib/api";
	import * as Card from "$lib/components/ui/card/index.js";
	import { Button } from "$lib/components/ui/button/index.js";
	import { Input } from "$lib/components/ui/input/index.js";
	import { Label } from "$lib/components/ui/label/index.js";
	import { Switch } from "$lib/components/ui/switch/index.js";
	import { Badge } from "$lib/components/ui/badge/index.js";

	let config = $state<ActiveHoursConfig>({ day_start: 7, day_end: 20, twenty_four_seven: false });
	let vacation = $state<VacationMode>({ active: false, substitute_phone: "", note: "" });
	let loading = $state(true);
	let saving = $state(false);
	let savingVacation = $state(false);
	let error = $state("");
	let success = $state("");

	async function load() {
		try {
			const [hours, vac] = await Promise.all([getActiveHours(), getVacationMode()]);
			config = hours;
			vacation = vac;
			error = "";
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	onMount(load);

	async function save() {
		saving = true;
		success = "";
		error = "";
		try {
			await updateActiveHours(config);
			success = "Einstellungen gespeichert";
			setTimeout(() => { success = ""; }, 3000);
		} catch (e: any) {
			error = e.message;
		} finally {
			saving = false;
		}
	}

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

	const currentMode = $derived(
		config.twenty_four_seven ? "24/7" : (() => {
			const now = new Date();
			const hour = now.getHours();
			return (hour >= config.day_start && hour < config.day_end) ? "Tag" : "Nacht";
		})()
	);
</script>

<div class="space-y-8">
	<div>
		<h2 class="text-3xl font-bold tracking-tight">Einstellungen</h2>
		<p class="text-muted-foreground">Aktive Zeiten, Urlaubsmodus und Tarifmodus konfigurieren</p>
	</div>

	{#if error}
		<div class="rounded-md bg-red-50 p-4 text-red-800 text-sm">{error}</div>
	{/if}
	{#if success}
		<div class="rounded-md bg-green-50 p-4 text-green-800 text-sm">{success}</div>
	{/if}

	{#if loading}
		<p class="text-muted-foreground">Laden...</p>
	{:else}
		<div class="grid gap-6 max-w-xl">
			<!-- Current mode display -->
			<Card.Root>
				<Card.Header>
					<Card.Title class="text-lg">Aktueller Modus</Card.Title>
				</Card.Header>
				<Card.Content>
					<div class="flex gap-2">
						<Badge variant={currentMode === "Nacht" ? "destructive" : "default"} class="text-base px-4 py-1">
							{currentMode}
						</Badge>
						{#if vacation.active}
							<Badge class="bg-orange-100 text-orange-800 border-orange-200 text-base px-4 py-1">Urlaub</Badge>
						{/if}
					</div>
				</Card.Content>
			</Card.Root>

			<!-- Vacation mode -->
			<Card.Root>
				<Card.Header>
					<Card.Title class="text-lg">Urlaubsmodus</Card.Title>
					<Card.Description>Alle Anrufe an eine Vertretungsnummer weiterleiten</Card.Description>
				</Card.Header>
				<Card.Content>
					<div class="grid gap-4">
						<div class="flex items-center gap-3">
							<Switch bind:checked={vacation.active} />
							<span class="text-sm">{vacation.active ? "Aktiviert" : "Deaktiviert"}</span>
						</div>
						{#if vacation.active}
							<div class="grid gap-2">
								<Label for="substitute_phone">Vertretungs-Telefon</Label>
								<Input id="substitute_phone" bind:value={vacation.substitute_phone} placeholder="+49..." />
							</div>
							<div class="grid gap-2">
								<Label for="vacation_note">Notiz</Label>
								<Input id="vacation_note" bind:value={vacation.note} placeholder="z.B. Urlaub bis 20.02." />
							</div>
						{/if}
						<Button onclick={saveVacation} disabled={savingVacation}>
							{savingVacation ? "Speichern..." : "Urlaubsmodus speichern"}
						</Button>
					</div>
				</Card.Content>
			</Card.Root>

			<!-- Active hours -->
			<Card.Root>
				<Card.Header>
					<Card.Title class="text-lg">Aktive Zeiten</Card.Title>
					<Card.Description>Tagestarif gilt zwischen diesen Uhrzeiten</Card.Description>
				</Card.Header>
				<Card.Content>
					<div class="grid grid-cols-2 gap-4">
						<div class="grid gap-2">
							<Label for="day_start">Start (Uhr)</Label>
							<Input id="day_start" type="number" bind:value={config.day_start} disabled={config.twenty_four_seven} />
						</div>
						<div class="grid gap-2">
							<Label for="day_end">Ende (Uhr)</Label>
							<Input id="day_end" type="number" bind:value={config.day_end} disabled={config.twenty_four_seven} />
						</div>
					</div>
				</Card.Content>
			</Card.Root>

			<!-- 24/7 toggle -->
			<Card.Root>
				<Card.Header>
					<Card.Title class="text-lg">24/7 Modus</Card.Title>
					<Card.Description>Wenn aktiviert, gilt immer der Tagestarif</Card.Description>
				</Card.Header>
				<Card.Content>
					<div class="flex items-center gap-3">
						<Switch bind:checked={config.twenty_four_seven} />
						<span class="text-sm">{config.twenty_four_seven ? "Aktiviert" : "Deaktiviert"}</span>
					</div>
				</Card.Content>
			</Card.Root>

			<Button onclick={save} disabled={saving}>
				{saving ? "Speichern..." : "Speichern"}
			</Button>
		</div>
	{/if}
</div>
