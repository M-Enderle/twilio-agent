<script lang="ts">
	import { page } from "$app/state";
	import { goto } from "$app/navigation";
	import { getCalls } from "$lib/api";
	import { formatPhone, formatDateTime, formatDateTimeShort } from "$lib/utils";
	import type { CallSummary } from "$lib/types";
	import * as Card from "$lib/components/ui/card/index.js";
	import { Skeleton } from "$lib/components/ui/skeleton/index.js";
	import AlertBanner from "$lib/components/AlertBanner.svelte";
	import CallDetailModal from "$lib/components/CallDetailModal.svelte";
	import PhoneIcon from "@lucide/svelte/icons/phone";
	import PhoneForwardedIcon from "@lucide/svelte/icons/phone-forwarded";
	import ChevronRightIcon from "@lucide/svelte/icons/chevron-right";
	import { getSelectedService, getServiceVersion } from "$lib/service.svelte";

	let calls = $state<CallSummary[]>([]);
	let loading = $state(true);
	let error = $state("");
	let modalOpen = $state(false);
	let selectedNumber = $state("");
	let selectedTimestamp = $state("");

	const POLL_INTERVAL = 5000;
	const MAX_CONSECUTIVE_ERRORS = 5;
	let consecutiveErrors = 0;

	async function loadCalls() {
		try {
			const selectedService = getSelectedService();
			const result = await getCalls(selectedService);
			calls = result.calls;
			error = "";
			consecutiveErrors = 0;
		} catch (e) {
			consecutiveErrors++;
			error = e instanceof Error ? e.message : "Ein unbekannter Fehler ist aufgetreten.";
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		// Reload calls when service changes
		const serviceVersion = getServiceVersion();
		loadCalls();
		const interval = setInterval(() => {
			if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) return;
			loadCalls();
		}, POLL_INTERVAL);
		return () => clearInterval(interval);
	});

	$effect(() => {
		const nummer = page.url.searchParams.get("nummer");
		const ts = page.url.searchParams.get("ts");
		if (nummer && ts) {
			selectedNumber = nummer;
			selectedTimestamp = ts;
			modalOpen = true;
		}
	});

	function openCall(call: CallSummary) {
		selectedNumber = call.number;
		selectedTimestamp = call.timestamp;
		modalOpen = true;
		goto(`/anrufe?nummer=${call.number}&ts=${call.timestamp}`, { replaceState: true });
	}

	function onModalClose() {
		modalOpen = false;
		goto("/anrufe", { replaceState: true });
	}

	function formatLocation(loc: Record<string, unknown> | string | null | undefined): string | null {
		if (!loc) return null;
		if (typeof loc === "object" && loc.formatted_address) return String(loc.formatted_address);
		if (typeof loc === "string" && loc.trim()) return loc;
		return null;
	}

	const liveCalls = $derived(calls.filter((c) => c.live === true).length);
</script>

<div class="space-y-4 sm:space-y-6">
	<div>
		<h2 class="text-2xl sm:text-3xl font-bold tracking-tight">Anrufe</h2>
		<p class="text-muted-foreground text-sm" aria-live="polite">
			{calls.length} {calls.length === 1 ? "Anruf" : "Anrufe"} gesamt{#if liveCalls > 0}<span class="text-green-600 font-medium">&nbsp;&middot; {liveCalls} live</span>{/if}
		</p>
	</div>

	<AlertBanner type="error" message={error} />

	{#if loading && calls.length === 0}
		<div class="rounded-xl border bg-card shadow-sm divide-y">
			{#each Array(5) as _}
				<div class="flex items-center gap-3 px-4 py-3">
					<Skeleton class="h-2.5 w-2.5 rounded-full shrink-0" />
					<div class="flex-1 space-y-1.5">
						<Skeleton class="h-4 w-28" />
						<Skeleton class="h-3 w-40 sm:hidden" />
					</div>
					<Skeleton class="h-3 w-24 hidden sm:block" />
				</div>
			{/each}
		</div>
	{:else if calls.length === 0}
		<div class="rounded-xl border bg-card shadow-sm flex flex-col items-center justify-center py-16 gap-3">
			<div class="p-3 rounded-full bg-muted">
				<PhoneIcon class="h-6 w-6 text-muted-foreground" />
			</div>
			<p class="text-muted-foreground text-sm">Keine Anrufe vorhanden.</p>
		</div>
	{:else}
		<div class="rounded-xl border bg-card shadow-sm divide-y">
			{#each calls as call}
				{@const location = formatLocation(call.location)}
				{@const isLive = call.live === true}
				<button
					class="w-full flex items-center gap-3 px-3 sm:px-4 py-2.5 text-left hover:bg-muted/40 active:bg-muted/60 transition-colors cursor-pointer first:rounded-t-xl last:rounded-b-xl"
					onclick={() => openCall(call)}
				>
					<!-- Status dot -->
					<div class="shrink-0">
						{#if isLive}
							<span class="relative flex h-2.5 w-2.5">
								<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-500 opacity-75"></span>
								<span class="relative inline-flex rounded-full h-2.5 w-2.5 bg-green-500"></span>
							</span>
						{:else}
							<span class="inline-flex rounded-full h-2.5 w-2.5 bg-muted-foreground/30"></span>
						{/if}
					</div>

					<!-- Mobile: stacked layout -->
					<div class="flex-1 min-w-0 sm:hidden">
						<div class="flex items-center gap-2">
							<span class="font-medium text-sm">{formatPhone(call.phone || call.number)}</span>
							{#if call.intent}
								<span class="text-xs text-muted-foreground capitalize truncate">{call.intent}</span>
							{/if}
						</div>
						<div class="flex items-center gap-2 text-xs text-muted-foreground mt-0.5">
							<span>{formatDateTimeShort(call.start_time)}</span>
							{#if call.transferred_to}
								<span class="flex items-center gap-0.5">
									<PhoneForwardedIcon class="h-3 w-3" />
									{call.transferred_to}
								</span>
							{/if}
						</div>
					</div>

					<!-- Desktop: single-line layout -->
					<span class="font-medium text-sm w-36 shrink-0 hidden sm:inline">{formatPhone(call.phone || call.number)}</span>
					<span class="text-xs text-muted-foreground w-36 shrink-0 hidden sm:inline">{formatDateTime(call.start_time)}</span>
					<span class="text-xs text-muted-foreground truncate flex-1 hidden sm:inline">
						{call.intent || ""}
						{#if call.intent && location}&ensp;&middot;&ensp;{/if}
						{location || ""}
					</span>
					{#if call.transferred_to}
						<span class="text-xs text-muted-foreground items-center gap-1 shrink-0 hidden sm:flex">
							<PhoneForwardedIcon class="h-3 w-3" />
							{call.transferred_to}
						</span>
					{/if}

					<ChevronRightIcon class="h-4 w-4 text-muted-foreground/30 shrink-0" />
				</button>
			{/each}
		</div>
	{/if}
</div>

{#if modalOpen}
	<CallDetailModal
		number={selectedNumber}
		timestamp={selectedTimestamp}
		bind:open={modalOpen}
		onclose={onModalClose}
	/>
{/if}
