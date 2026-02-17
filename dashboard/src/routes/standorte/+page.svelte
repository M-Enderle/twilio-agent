<script lang="ts">
	import { page } from "$app/state";
	import { goto } from "$app/navigation";
	import type { Standort } from "$lib/types";
	import { SERVICES } from "$lib/types";
	import { getStandorte } from "$lib/api";
	import { getSelectedService, getServiceVersion } from "$lib/service.svelte";
	import StandortMap from "$lib/components/StandortMap.svelte";
	import StandortDetailModal from "$lib/components/StandortDetailModal.svelte";
	import { Button } from "$lib/components/ui/button/index.js";
	import RefreshCwIcon from "@lucide/svelte/icons/refresh-cw";

	let standorte = $state<Standort[]>([]);
	let loading = $state(true);
	let error = $state("");
	let mapRef = $state<{ refresh: () => void } | null>(null);

	// Modal state
	let modalOpen = $state(false);
	let selectedStandortId = $state<string | null>(null);
	let isNewStandort = $state(false);

	const serviceId = $derived(getSelectedService());
	const serviceLabel = $derived(SERVICES.find((s) => s.id === serviceId)?.label ?? serviceId);

	async function loadStandorte() {
		loading = true;
		try {
			standorte = await getStandorte(serviceId);
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
		loadStandorte();
	});

	// URL sync: auto-open modal from query params
	$effect(() => {
		const id = page.url.searchParams.get("id");
		const neu = page.url.searchParams.get("neu");
		if (neu) {
			selectedStandortId = null;
			isNewStandort = true;
			modalOpen = true;
		} else if (id) {
			selectedStandortId = id;
			isNewStandort = false;
			modalOpen = true;
		}
	});

	function openStandort(id: string) {
		selectedStandortId = id;
		isNewStandort = false;
		modalOpen = true;
		goto(`/standorte?id=${id}`, { replaceState: true });
	}

	function openNewStandort() {
		selectedStandortId = null;
		isNewStandort = true;
		modalOpen = true;
		goto("/standorte?neu=1", { replaceState: true });
	}

	function onModalClose() {
		modalOpen = false;
		goto("/standorte", { replaceState: true });
	}

	function onModalSave() {
		loadStandorte();
	}

	function refreshMap() {
		mapRef?.refresh();
	}

	const totalStandorte = $derived(standorte.length);
</script>

<div class="h-[calc(100vh-8rem)] flex flex-col">
	<div class="flex items-center justify-between mb-4">
		<div>
			<h2 class="text-2xl sm:text-3xl font-bold tracking-tight">Standorte</h2>
			<p class="text-muted-foreground text-sm">
				{totalStandorte} {totalStandorte === 1 ? "Standort" : "Standorte"} ({serviceLabel})
			</p>
		</div>
		<div class="flex items-center gap-3">
			<Button variant="outline" size="icon" onclick={refreshMap} title="Karte neu laden" aria-label="Karte neu laden">
				<RefreshCwIcon class="h-4 w-4" />
			</Button>
			<Button onclick={openNewStandort}>+ Standort</Button>
		</div>
	</div>

	{#if error}
		<div class="rounded-lg bg-red-50 border border-red-200 p-3 sm:p-4 text-red-800 text-sm mb-4">
			{error}
		</div>
	{/if}

	{#if loading && standorte.length === 0}
		<div class="flex-1 flex items-center justify-center">
			<p class="text-muted-foreground">Karte wird geladen...</p>
		</div>
	{:else}
		<div class="flex-1 rounded-lg overflow-hidden border">
			<StandortMap
				standorte={standorte}
				{serviceId}
				onstandortclick={openStandort}
				bind:this={mapRef}
			/>
		</div>
	{/if}
</div>

{#if modalOpen}
	<StandortDetailModal
		standortId={selectedStandortId}
		isNew={isNewStandort}
		bind:open={modalOpen}
		{serviceId}
		onclose={onModalClose}
		onsave={onModalSave}
	/>
{/if}
