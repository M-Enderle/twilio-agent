<script lang="ts">
	import { onMount } from "svelte";
	import type { PricingConfig, ServicePricing, PricingTier, ActiveHoursConfig } from "$lib/types";
	import { getPricing, updatePricing, getActiveHours, updateActiveHours } from "$lib/api";
	import * as Card from "$lib/components/ui/card/index.js";
	import { Button } from "$lib/components/ui/button/index.js";
	import { Input } from "$lib/components/ui/input/index.js";
	import { Label } from "$lib/components/ui/label/index.js";
	import { Separator } from "$lib/components/ui/separator/index.js";
	import KeyIcon from "@lucide/svelte/icons/key";
	import CarIcon from "@lucide/svelte/icons/car";
	import SunIcon from "@lucide/svelte/icons/sun";
	import MoonIcon from "@lucide/svelte/icons/moon";
	import ClockIcon from "@lucide/svelte/icons/clock";
	import PlusIcon from "@lucide/svelte/icons/plus";
	import TrashIcon from "@lucide/svelte/icons/trash";
	import CheckIcon from "@lucide/svelte/icons/check";
	import LoaderIcon from "@lucide/svelte/icons/loader";
	import AlertCircleIcon from "@lucide/svelte/icons/alert-circle";
	import EuroIcon from "@lucide/svelte/icons/euro";

	let config = $state<PricingConfig>({
		locksmith: { tiers: [], fallbackDayPrice: 0, fallbackNightPrice: 0 },
		towing: { tiers: [], fallbackDayPrice: 0, fallbackNightPrice: 0 },
	});
	let activeHours = $state<ActiveHoursConfig>({ day_start: 7, day_end: 20, twenty_four_seven: false });
	let loading = $state(true);
	let saving = $state(false);
	let savingHours = $state(false);
	let error = $state("");
	let success = $state("");

	async function load() {
		try {
			const [pricing, hours] = await Promise.all([getPricing(), getActiveHours()]);
			config = pricing;
			activeHours = hours;
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
			await updatePricing(config);
			success = "Preise gespeichert";
			setTimeout(() => { success = ""; }, 3000);
		} catch (e: any) {
			error = e.message;
		} finally {
			saving = false;
		}
	}

	async function saveHours() {
		savingHours = true;
		success = "";
		error = "";
		try {
			await updateActiveHours(activeHours);
			success = "Tarifzeiten gespeichert";
			setTimeout(() => { success = ""; }, 3000);
		} catch (e: any) {
			error = e.message;
		} finally {
			savingHours = false;
		}
	}

	const currentHour = $derived(new Date().getHours());
	const dayStartPercent = $derived((activeHours.day_start / 24) * 100);
	const dayEndPercent = $derived((activeHours.day_end / 24) * 100);
	const currentHourPercent = $derived((currentHour / 24) * 100);
	const currentMode = $derived(currentHour >= activeHours.day_start && currentHour < activeHours.day_end ? "Tag" : "Nacht");

	function addTier(service: "locksmith" | "towing") {
		const lastTier = config[service].tiers[config[service].tiers.length - 1];
		const newMinutes = lastTier ? lastTier.minutes + 10 : 10;
		config[service].tiers = [
			...config[service].tiers,
			{ minutes: newMinutes, dayPrice: 0, nightPrice: 0 },
		];
	}

	function removeTier(service: "locksmith" | "towing", index: number) {
		config[service].tiers = config[service].tiers.filter((_, i) => i !== index);
	}

	function updateTier(service: "locksmith" | "towing", index: number, field: keyof PricingTier, value: number) {
		config[service].tiers[index][field] = value;
	}

	const serviceLabels = {
		locksmith: { name: "Schlüsseldienst", icon: KeyIcon, color: "amber" },
		towing: { name: "Abschleppdienst", icon: CarIcon, color: "blue" },
	};
</script>

<div class="space-y-8 max-w-4xl mx-auto">
	<div>
		<h2 class="text-3xl font-bold tracking-tight">Preise</h2>
		<p class="text-muted-foreground">Preisgestaltung nach Entfernung und Tageszeit</p>
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
		<!-- Tarifzeiten Card -->
		<Card.Root>
			<Card.Header>
				<div class="flex items-center justify-between">
					<div class="flex items-center gap-3">
						<div class="p-2 rounded-lg bg-slate-100">
							<ClockIcon class="h-5 w-5 text-slate-600" />
						</div>
						<div>
							<Card.Title>Tarifzeiten</Card.Title>
							<Card.Description>Zeitfenster für Tag- und Nachttarif festlegen</Card.Description>
						</div>
					</div>
					<div class={currentMode === "Nacht"
						? "flex items-center gap-2 px-3 py-1.5 rounded-full bg-indigo-100 text-indigo-700"
						: "flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-100 text-amber-700"}>
						{#if currentMode === "Nacht"}
							<MoonIcon class="h-4 w-4" />
						{:else}
							<SunIcon class="h-4 w-4" />
						{/if}
						<span class="text-sm font-medium">{currentMode === "Tag" ? "Tagestarif" : "Nachttarif"}</span>
					</div>
				</div>
			</Card.Header>
			<Card.Content>
				<div class="grid gap-5">
					<!-- Time inputs -->
					<div class="grid grid-cols-2 gap-4">
						<div class="grid gap-2">
							<Label for="day_start" class="flex items-center gap-2">
								<SunIcon class="h-4 w-4 text-amber-500" />
								Tagesbeginn
							</Label>
							<div class="relative">
								<Input id="day_start" type="number" min="0" max="23" bind:value={activeHours.day_start} class="pr-12" />
								<span class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">Uhr</span>
							</div>
						</div>
						<div class="grid gap-2">
							<Label for="day_end" class="flex items-center gap-2">
								<MoonIcon class="h-4 w-4 text-indigo-500" />
								Tagesende
							</Label>
							<div class="relative">
								<Input id="day_end" type="number" min="0" max="24" bind:value={activeHours.day_end} class="pr-12" />
								<span class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">Uhr</span>
							</div>
						</div>
					</div>

					<!-- Visual time bar -->
					<div class="space-y-2">
						<p class="text-sm text-muted-foreground">Tarifübersicht</p>
						<div class="relative h-10 rounded-lg overflow-hidden bg-indigo-100">
							<!-- Day period -->
							<div
								class="absolute top-0 bottom-0 bg-gradient-to-r from-amber-300 to-amber-400"
								style="left: {dayStartPercent}%; width: {dayEndPercent - dayStartPercent}%"
							></div>
							<!-- Current time indicator -->
							<div
								class="absolute top-0 bottom-0 w-0.5 bg-red-500 z-10"
								style="left: {currentHourPercent}%"
							>
								<div class="absolute -top-1 left-1/2 -translate-x-1/2 w-2 h-2 rounded-full bg-red-500"></div>
							</div>
						</div>
						<div class="flex justify-between text-xs text-muted-foreground">
							<span>0:00</span>
							<span>6:00</span>
							<span>12:00</span>
							<span>18:00</span>
							<span>24:00</span>
						</div>
						<div class="flex items-center gap-4 text-xs pt-2">
							<div class="flex items-center gap-1.5">
								<div class="w-3 h-3 rounded bg-gradient-to-r from-amber-300 to-amber-400"></div>
								<span>Tagestarif</span>
							</div>
							<div class="flex items-center gap-1.5">
								<div class="w-3 h-3 rounded bg-indigo-100"></div>
								<span>Nachttarif</span>
							</div>
							<div class="flex items-center gap-1.5">
								<div class="w-3 h-3 rounded bg-red-500"></div>
								<span>Jetzt</span>
							</div>
						</div>
					</div>
				</div>
			</Card.Content>
			<Card.Footer>
				<Button onclick={saveHours} disabled={savingHours} class="w-full">
					{#if savingHours}
						<LoaderIcon class="h-4 w-4 mr-2 animate-spin" />
						Speichern...
					{:else}
						<CheckIcon class="h-4 w-4 mr-2" />
						Tarifzeiten speichern
					{/if}
				</Button>
			</Card.Footer>
		</Card.Root>

		<Separator />

		<div class="grid gap-6">
			{#each (["locksmith", "towing"] as const) as service}
				{@const label = serviceLabels[service]}
				<Card.Root>
					<Card.Header>
						<div class="flex items-center gap-3">
							<div class="p-2 rounded-lg bg-slate-100">
								<label.icon class="h-5 w-5 text-slate-600" />
							</div>
							<div>
								<Card.Title>{label.name}</Card.Title>
								<Card.Description>Preisstaffelung nach Anfahrtszeit</Card.Description>
							</div>
						</div>
					</Card.Header>
					<Card.Content>
						<div class="space-y-6">
							<!-- Tiers table -->
							<table class="w-full">
								<thead>
									<tr class="text-sm font-medium text-muted-foreground">
										<th class="text-left pb-3 font-medium">
											<span class="flex items-center gap-2">
												<ClockIcon class="h-4 w-4" />
												Bis Minuten
											</span>
										</th>
										<th class="text-left pb-3 font-medium">
											<span class="flex items-center gap-2">
												<SunIcon class="h-4 w-4 text-amber-500" />
												Tagpreis
											</span>
										</th>
										<th class="text-left pb-3 font-medium">
											<span class="flex items-center gap-2">
												<MoonIcon class="h-4 w-4 text-indigo-500" />
												Nachtpreis
											</span>
										</th>
										<th class="w-10"></th>
									</tr>
								</thead>
								<tbody>
									{#each config[service].tiers as tier, index}
										<tr>
											<td class="py-2 pr-3">
												<div class="relative">
													<Input
														type="number"
														min="1"
														value={tier.minutes}
														onchange={(e) => updateTier(service, index, "minutes", parseInt((e.target as HTMLInputElement).value) || 0)}
														class="pr-12"
													/>
													<span class="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">min</span>
												</div>
											</td>
											<td class="py-2 pr-3">
												<div class="relative">
													<Input
														type="number"
														min="0"
														step="10"
														value={tier.dayPrice}
														onchange={(e) => updateTier(service, index, "dayPrice", parseInt((e.target as HTMLInputElement).value) || 0)}
														class="pr-8"
													/>
													<EuroIcon class="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
												</div>
											</td>
											<td class="py-2 pr-3">
												<div class="relative">
													<Input
														type="number"
														min="0"
														step="10"
														value={tier.nightPrice}
														onchange={(e) => updateTier(service, index, "nightPrice", parseInt((e.target as HTMLInputElement).value) || 0)}
														class="pr-8"
													/>
													<EuroIcon class="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
												</div>
											</td>
											<td class="py-2">
												<Button variant="ghost" size="icon" onclick={() => removeTier(service, index)} class="text-red-500 hover:text-red-700 hover:bg-red-50">
													<TrashIcon class="h-4 w-4" />
												</Button>
											</td>
										</tr>
									{/each}
								</tbody>
							</table>

							<!-- Add tier button -->
							<Button variant="outline" onclick={() => addTier(service)} class="w-full">
								<PlusIcon class="h-4 w-4 mr-2" />
								Preisstufe hinzufügen
							</Button>

							<Separator />

							<!-- Fallback prices -->
							<div class="space-y-4">
								<p class="text-sm font-medium text-muted-foreground">Fallback-Preise (wenn Entfernung alle Stufen überschreitet)</p>
								<div class="grid grid-cols-2 gap-4">
									<div class="space-y-2">
										<Label class="flex items-center gap-2">
											<SunIcon class="h-4 w-4 text-amber-500" />
											Tagpreis
										</Label>
										<div class="relative">
											<Input
												type="number"
												min="0"
												step="10"
												bind:value={config[service].fallbackDayPrice}
												class="pr-8"
											/>
											<EuroIcon class="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
										</div>
									</div>
									<div class="space-y-2">
										<Label class="flex items-center gap-2">
											<MoonIcon class="h-4 w-4 text-indigo-500" />
											Nachtpreis
										</Label>
										<div class="relative">
											<Input
												type="number"
												min="0"
												step="10"
												bind:value={config[service].fallbackNightPrice}
												class="pr-8"
											/>
											<EuroIcon class="absolute right-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
										</div>
									</div>
								</div>
							</div>
						</div>
					</Card.Content>
				</Card.Root>
			{/each}
		</div>

		<div class="flex justify-end">
			<Button onclick={save} disabled={saving} size="lg">
				{#if saving}
					<LoaderIcon class="h-4 w-4 mr-2 animate-spin" />
					Speichern...
				{:else}
					<CheckIcon class="h-4 w-4 mr-2" />
					Alle Preise speichern
				{/if}
			</Button>
		</div>
	{/if}
</div>
