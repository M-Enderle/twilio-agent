<script lang="ts">
	import type { Announcements } from "$lib/types";
	import { SERVICES } from "$lib/types";
	import { getAnnouncements, updateAnnouncements } from "$lib/api";
	import { getSelectedService, getServiceVersion } from "$lib/service.svelte";
	import { Button } from "$lib/components/ui/button/index.js";
	import AlertBanner from "$lib/components/AlertBanner.svelte";
	import CheckIcon from "@lucide/svelte/icons/check";
	import LoaderIcon from "@lucide/svelte/icons/loader";
	import ChevronDownIcon from "@lucide/svelte/icons/chevron-down";
	import ChevronRightIcon from "@lucide/svelte/icons/chevron-right";
	import RotateCcwIcon from "@lucide/svelte/icons/rotate-ccw";
	import MessageCircleIcon from "@lucide/svelte/icons/message-circle";
	import MapPinIcon from "@lucide/svelte/icons/map-pin";
	import SmartphoneIcon from "@lucide/svelte/icons/smartphone";
	import ReceiptIcon from "@lucide/svelte/icons/receipt";
	import PhoneForwardedIcon from "@lucide/svelte/icons/phone-forwarded";
	import AlertTriangleIcon from "@lucide/svelte/icons/alert-triangle";
	import PhoneOutgoingIcon from "@lucide/svelte/icons/phone-outgoing";
	import SendIcon from "@lucide/svelte/icons/send";

	const DEFAULTS: Announcements = {
		// Begrüßung
		greeting: "Hallo, hier ist die Notdienststation. Wie kann ich dir helfen?",
		// Adresse erfassen
		address_request: "Nenne mir bitte deine Adresse mit Straße, Hausnummer und Wohnort.",
		address_processing: "Einen Moment, ich prüfe deine Eingabe.",
		address_confirm: "Als Ort habe ich {place_phrase} erkannt. Ist das richtig?",
		address_confirm_prompt: "Bitte bestätige mit ja oder nein, ob die Adresse korrekt ist.",
		// PLZ Fallback
		zipcode_request: "Bitte gib die Postleitzahl deines Ortes über den Nummernblock ein.",
		plz_invalid_format: "Die Postleitzahl konnte nicht erkannt werden. Bitte versuche es erneut.",
		plz_outside_area: "Diese Postleitzahl liegt außerhalb unseres Servicegebiets.",
		plz_not_found: "Diese Postleitzahl konnte nicht gefunden werden.",
		// SMS Standort
		sms_offer: "Wir können dir eine SMS mit einem Link zusenden, der uns deinen Standort übermittelt. Möchtest du das?",
		sms_sent_confirmation: "Ich habe dir eine SMS mit einem Link zum Teilen deines Standorts gesendet. Auf Wiederhören.",
		// Preisangebot
		price_offer: "Wir können dir einen Dienstleister für {price_words} Euro anbieten. Die Ankunftszeit beträgt etwa {minutes_words} Minuten.",
		price_offer_prompt: "Möchtest du mit dem Dienstleister verbunden werden? Bitte antworte mit ja oder nein.",
		connection_declined: "Verstanden. Gibt es noch etwas, womit ich dir helfen kann?",
		connection_timeout: "Ich habe deine Antwort nicht verstanden.",
		// Transfer
		transfer_message: "Ich verbinde Sie jetzt.",
		no_agents_available: "Leider ist momentan niemand erreichbar. Bitte versuchen Sie es in 5 Minuten erneut.",
	};

	interface SpeechNode {
		key: keyof Announcements;
		label: string;
		description: string;
		placeholders: string[];
	}

	interface Phase {
		id: number;
		title: string;
		icon: typeof MessageCircleIcon;
		color: string;
		bgGradient: string;
		borderColor: string;
		dotColor: string;
		badgeColor: string;
		nodes: SpeechNode[];
		branchAfter?: string;
	}

	const PHASES: Phase[] = [
		{
			id: 1,
			title: "Begrüßung",
			icon: MessageCircleIcon,
			color: "text-sky-600",
			bgGradient: "from-sky-50 to-blue-50",
			borderColor: "border-sky-200",
			dotColor: "bg-sky-500",
			badgeColor: "bg-sky-100 text-sky-700",
			nodes: [
				{ key: "greeting", label: "Begrüßung", description: "Erste Ansage beim Anruf", placeholders: [] },
			],
		},
		{
			id: 2,
			title: "Adresse erfassen",
			icon: MapPinIcon,
			color: "text-amber-600",
			bgGradient: "from-amber-50 to-yellow-50",
			borderColor: "border-amber-200",
			dotColor: "bg-amber-500",
			badgeColor: "bg-amber-100 text-amber-700",
			nodes: [
				{ key: "address_request", label: "Adresse anfragen", description: "Aufforderung die Adresse zu nennen", placeholders: [] },
				{ key: "address_processing", label: "Verarbeitung", description: "Hinweis während Adresse geprüft wird", placeholders: [] },
				{ key: "address_confirm", label: "Adresse bestätigen", description: "Erkannte Adresse zur Bestätigung vorlesen", placeholders: ["{place_phrase}"] },
				{ key: "address_confirm_prompt", label: "Bestätigung erfragen", description: "Ja/Nein-Abfrage zur Adresse", placeholders: [] },
			],
		},
		{
			id: 3,
			title: "PLZ Fallback",
			icon: AlertTriangleIcon,
			color: "text-orange-600",
			bgGradient: "from-orange-50 to-amber-50",
			borderColor: "border-orange-200",
			dotColor: "bg-orange-500",
			badgeColor: "bg-orange-100 text-orange-700",
			nodes: [
				{ key: "zipcode_request", label: "PLZ erfragen", description: "Postleitzahl über Nummernblock anfordern", placeholders: [] },
				{ key: "plz_invalid_format", label: "PLZ ungültig", description: "PLZ konnte nicht erkannt werden", placeholders: [] },
				{ key: "plz_outside_area", label: "Außerhalb Gebiet", description: "PLZ liegt außerhalb des Servicegebiets", placeholders: [] },
				{ key: "plz_not_found", label: "PLZ nicht gefunden", description: "PLZ konnte nicht georeferenziert werden", placeholders: [] },
			],
		},
		{
			id: 4,
			title: "SMS-Standort",
			icon: SmartphoneIcon,
			color: "text-violet-600",
			bgGradient: "from-violet-50 to-purple-50",
			borderColor: "border-violet-200",
			dotColor: "bg-violet-500",
			badgeColor: "bg-violet-100 text-violet-700",
			nodes: [
				{ key: "sms_offer", label: "SMS anbieten", description: "Standort-Link per SMS vorschlagen", placeholders: [] },
				{ key: "sms_sent_confirmation", label: "SMS versendet", description: "Bestätigung dass SMS gesendet wurde", placeholders: [] },
			],
		},
		{
			id: 5,
			title: "Preisangebot & Verbindung",
			icon: ReceiptIcon,
			color: "text-emerald-600",
			bgGradient: "from-emerald-50 to-green-50",
			borderColor: "border-emerald-200",
			dotColor: "bg-emerald-500",
			badgeColor: "bg-emerald-100 text-emerald-700",
			nodes: [
				{ key: "price_offer", label: "Preisansage", description: "Preis und Ankunftszeit nennen", placeholders: ["{price_words}", "{minutes_words}"] },
				{ key: "price_offer_prompt", label: "Verbindung anfragen", description: "Fragen ob Verbindung gewünscht", placeholders: [] },
				{ key: "connection_declined", label: "Verbindung abgelehnt", description: "Wenn Kunde Verbindung ablehnt", placeholders: [] },
				{ key: "connection_timeout", label: "Keine Antwort", description: "Antwort nicht verstanden", placeholders: [] },
			],
		},
		{
			id: 6,
			title: "Weiterleitung",
			icon: PhoneForwardedIcon,
			color: "text-slate-600",
			bgGradient: "from-slate-50 to-gray-50",
			borderColor: "border-slate-200",
			dotColor: "bg-slate-500",
			badgeColor: "bg-slate-100 text-slate-700",
			nodes: [
				{ key: "transfer_message", label: "Verbindungsansage", description: "Weiterleitung zu Mitarbeiter oder Dienstleister", placeholders: [] },
				{ key: "no_agents_available", label: "Niemand erreichbar", description: "Wenn kein Mitarbeiter erreichbar ist", placeholders: [] },
			],
		},
	];

	let announcements = $state<Announcements>({ ...DEFAULTS });
	let loading = $state(true);
	let saving = $state(false);
	let error = $state("");
	let success = $state("");
	let expandedPhases = $state<Set<number>>(new Set([1]));

	const serviceId = $derived(getSelectedService());
	const serviceLabel = $derived(SERVICES.find((s) => s.id === serviceId)?.label ?? serviceId);

	function togglePhase(id: number) {
		if (expandedPhases.has(id)) {
			expandedPhases = new Set();
		} else {
			expandedPhases = new Set([id]);
		}
	}

	async function load() {
		loading = true;
		try {
			announcements = await getAnnouncements(serviceId);
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

	async function saveAll() {
		saving = true;
		success = "";
		error = "";
		try {
			await updateAnnouncements(serviceId, announcements);
			success = "Ansagen gespeichert";
			setTimeout(() => { success = ""; }, 3000);
		} catch (e) {
			error = e instanceof Error ? e.message : "Speichern fehlgeschlagen.";
		} finally {
			saving = false;
		}
	}

	function resetPhase(phase: Phase) {
		for (const node of phase.nodes) {
			announcements[node.key] = DEFAULTS[node.key];
		}
	}
</script>

<div class="space-y-6 max-w-4xl mx-auto">
	<div>
		<h2 class="text-3xl font-bold tracking-tight">Ansagen</h2>
		<p class="text-muted-foreground">Gesprächstexte bearbeiten ({serviceLabel})</p>
	</div>

	<AlertBanner type="error" message={error} />
	<AlertBanner type="success" message={success} />

	{#if loading}
		<div class="flex items-center justify-center py-12">
			<LoaderIcon class="h-8 w-8 animate-spin text-muted-foreground" />
		</div>
	{:else}
		<div class="relative">
			{#each PHASES as phase, phaseIdx}
				{@const isExpanded = expandedPhases.has(phase.id)}
				{@const nodeCount = phase.nodes.length}

				<!-- Phase Card -->
				<div class="relative mb-6">
					<!-- Connector arrow (between phases, not after last) -->
					{#if phaseIdx < PHASES.length - 1}
						<div class="absolute left-8 -bottom-6 w-0.5 h-6 bg-gradient-to-b from-muted-foreground/30 to-muted-foreground/10 z-0"></div>
					{/if}

					<div class="rounded-xl border {phase.borderColor} bg-gradient-to-br {phase.bgGradient} overflow-hidden shadow-sm">
						<!-- Phase Header -->
						<button
							class="w-full flex items-center gap-4 p-4 text-left hover:bg-black/[0.02] transition-colors"
							onclick={() => togglePhase(phase.id)}
						>
							<div class="flex items-center justify-center w-10 h-10 rounded-full bg-white shadow-sm border {phase.borderColor}">
								<phase.icon class="h-5 w-5 {phase.color}" />
							</div>
							<div class="flex-1 min-w-0">
								<div class="flex items-center gap-2">
									<span class="font-semibold text-sm">{phase.id}. {phase.title}</span>
									<span class="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium {phase.badgeColor}">
										{nodeCount} {nodeCount === 1 ? "Ansage" : "Ansagen"}
									</span>
								</div>
							</div>
							{#if isExpanded}
								<ChevronDownIcon class="h-5 w-5 text-muted-foreground shrink-0" />
							{:else}
								<ChevronRightIcon class="h-5 w-5 text-muted-foreground shrink-0" />
							{/if}
						</button>

						<!-- Expanded Content -->
						{#if isExpanded}
							<div class="px-4 pb-4 space-y-3">
								{#each phase.nodes as node}
									<div class="rounded-lg border bg-white/80 backdrop-blur-sm p-3 shadow-sm">
										<div class="flex items-center gap-2 mb-1">
											<span class="font-medium text-sm">{node.label}</span>
											<span class="text-xs text-muted-foreground">{node.description}</span>
										</div>
										<textarea
											class="w-full rounded-md border border-input bg-white px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-y min-h-[60px]"
											rows="2"
											bind:value={announcements[node.key]}
										></textarea>
										{#if node.placeholders.length > 0}
											<div class="flex flex-wrap gap-1 mt-2">
												{#each node.placeholders as ph}
													<span class="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-mono font-medium bg-violet-100 text-violet-700 border border-violet-200">{ph}</span>
												{/each}
											</div>
										{/if}
									</div>
								{/each}

								<!-- Reset phase button -->
								<div class="flex justify-end">
									<button
										class="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
										onclick={() => resetPhase(phase)}
									>
										<RotateCcwIcon class="h-3.5 w-3.5" />
										Standardwerte wiederherstellen
									</button>
								</div>
							</div>
						{/if}
					</div>
				</div>
			{/each}
		</div>

		<!-- Save All Button -->
		<div class="sticky bottom-4 pt-4">
			<Button onclick={saveAll} disabled={saving} class="w-full h-12 text-base shadow-lg">
				{#if saving}
					<LoaderIcon class="h-5 w-5 mr-2 animate-spin" />
					Speichern...
				{:else}
					<CheckIcon class="h-5 w-5 mr-2" />
					Alle Ansagen speichern
				{/if}
			</Button>
		</div>
	{/if}
</div>
