<script lang="ts">
	import { page } from "$app/state";
	import { goto } from "$app/navigation";
	import type { Standort, CallSummary } from "$lib/types";
	import { SERVICES } from "$lib/types";
	import { getStandorte, getCalls } from "$lib/api";
	import { getSelectedService, getServiceVersion } from "$lib/service.svelte";
	import StandortMap from "$lib/components/StandortMap.svelte";
	import StandortDetailModal from "$lib/components/StandortDetailModal.svelte";
	import { Button } from "$lib/components/ui/button/index.js";

	let standorte = $state<Standort[]>([]);
	let calls = $state<CallSummary[]>([]);
	let loading = $state(true);
	let error = $state("");

	// Modal state
	let modalOpen = $state(false);
	let selectedStandortId = $state<string | null>(null);
	let isNewStandort = $state(false);

	const serviceId = $derived(getSelectedService());
	const serviceLabel = $derived(SERVICES.find((s) => s.id === serviceId)?.label ?? serviceId);

	const POLL_INTERVAL = 30000; // Poll every 30 seconds for calls

	async function loadStandorte() {
		loading = true;
		try {
			const [standorteData, callsData] = await Promise.all([
				getStandorte(serviceId),
				getCalls(serviceId)
			]);
			standorte = standorteData;
			calls = callsData.calls;
			error = "";
		} catch (e) {
			error = e instanceof Error ? e.message : "Ein unbekannter Fehler ist aufgetreten.";
		} finally {
			loading = false;
		}
	}

	async function loadCallsOnly() {
		try {
			const callsData = await getCalls(serviceId);
			calls = callsData.calls;
		} catch (e) {
			// Silently fail for background polling
		}
	}

	$effect(() => {
		serviceId;
		getServiceVersion();
		loadStandorte();

		// Poll for call updates
		const interval = setInterval(loadCallsOnly, POLL_INTERVAL);
		return () => clearInterval(interval);
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
				{calls}
				{serviceId}
				onstandortclick={openStandort}
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
		{calls}
		{standorte}
		onclose={onModalClose}
		onsave={onModalSave}
	/>
{/if}
