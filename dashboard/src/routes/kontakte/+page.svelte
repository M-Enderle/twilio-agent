<script lang="ts">
	import { onMount } from "svelte";
	import type { ContactWithCoords, Category } from "$lib/types";
	import { getContacts } from "$lib/api";
	import ContactMap from "$lib/components/ContactMap.svelte";
	import { Button } from "$lib/components/ui/button/index.js";
	import RefreshCwIcon from "@lucide/svelte/icons/refresh-cw";
	import KeyIcon from "@lucide/svelte/icons/key";
	import TruckIcon from "@lucide/svelte/icons/truck";

	let contacts = $state<Record<Category, ContactWithCoords[]>>({
		locksmith: [],
		towing: [],
	});
	let loading = $state(true);
	let error = $state("");
	let selectedCategory = $state<Category>("locksmith");
	let mapRef = $state<{ refresh: () => void } | null>(null);

	async function loadContacts() {
		try {
			const raw = await getContacts();
			// Parse fallbacks_json for each contact
			for (const category of Object.keys(raw) as Category[]) {
				contacts[category] = raw[category].map((c) => ({
					...c,
					fallbacks: c.fallbacks_json ? JSON.parse(c.fallbacks_json) : [],
				}));
			}
			error = "";
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	onMount(loadContacts);

	function refreshMap() {
		mapRef?.refresh();
	}

	// Count non-fallback contacts with coordinates for display (filtered by category)
	const markerCount = $derived(
		contacts[selectedCategory]
			.filter((c) => !c.fallback && c.latitude && c.longitude).length
	);

	const totalContacts = $derived(
		contacts[selectedCategory]
			.filter((c) => !c.fallback).length
	);

	// Filtered contacts for map
	const filteredContacts = $derived({
		locksmith: selectedCategory === "locksmith" ? contacts.locksmith : [],
		towing: selectedCategory === "towing" ? contacts.towing : [],
	} as Record<Category, ContactWithCoords[]>);
</script>

<div class="h-[calc(100vh-8rem)] flex flex-col">
	<div class="flex items-center justify-between mb-4">
		<div>
			<h2 class="text-3xl font-bold tracking-tight">Kontakte</h2>
			<p class="text-muted-foreground">
				{markerCount} von {totalContacts} {selectedCategory === "locksmith" ? "Schlüsseldiensten" : "Abschleppdiensten"} auf der Karte
			</p>
		</div>
		<div class="flex items-center gap-3">
			<!-- Category Toggle -->
			<div class="flex rounded-lg border bg-muted p-1">
				<button
					class="flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-colors {selectedCategory === 'locksmith' ? 'bg-white shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'}"
					onclick={() => selectedCategory = "locksmith"}
				>
					<KeyIcon class="h-4 w-4" />
					Schlüsseldienst
				</button>
				<button
					class="flex items-center gap-2 px-3 py-1.5 rounded-md text-sm font-medium transition-colors {selectedCategory === 'towing' ? 'bg-white shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground'}"
					onclick={() => selectedCategory = "towing"}
				>
					<TruckIcon class="h-4 w-4" />
					Abschleppdienst
				</button>
			</div>
			<!-- Refresh Button -->
			<Button variant="outline" size="icon" onclick={refreshMap} title="Karte neu laden">
				<RefreshCwIcon class="h-4 w-4" />
			</Button>
			<Button href="/kontakte/neu">+ Kontakt</Button>
		</div>
	</div>

	{#if error}
		<div class="rounded-md bg-red-50 p-4 text-red-800 text-sm mb-4">
			{error}
		</div>
	{/if}

	{#if loading}
		<div class="flex-1 flex items-center justify-center">
			<p class="text-muted-foreground">Karte wird geladen...</p>
		</div>
	{:else}
		<div class="flex-1 rounded-lg overflow-hidden border">
			<ContactMap contacts={filteredContacts} category={selectedCategory} bind:this={mapRef} />
		</div>
	{/if}
</div>
