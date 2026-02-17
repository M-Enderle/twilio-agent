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
		greeting: "Hallo, hier ist die Notdienststation. Wie kann ich dir helfen?",
		intent_prompt: "Bitte beschreibe dein Anliegen damit ich dich mit dem richtigen Ansprechpartner verbinden kann.",
		intent_not_understood: "Leider konnte ich deine Anfrage nicht verstehen. Wie kann ich dir helfen?",
		intent_failed: "Leider konnte ich dein Anliegen wieder nicht verstehen. Ich verbinde dich mit einem Mitarbeiter.",
		address_request: "Nenne mir bitte deine Adresse mit Straße, Hausnummer und Wohnort.",
		address_processing: "Einen Moment, ich prüfe deine Eingabe.",
		address_confirm: "Als Ort habe ich {place_phrase} erkannt. Ist das richtig?",
		address_confirm_prompt: "Bitte bestätige mit ja oder nein, ob die Adresse korrekt ist.",
		zipcode_request: "Bitte gib die Postleitzahl deines Ortes über den Nummernblock ein.",
		sms_offer: "Wir können dir eine SMS mit einem Link zusenden, der uns deinen Standort übermittelt. Möchtest du das?",
		sms_confirm_prompt: "Möchtest du eine SMS mit dem Link erhalten?",
		sms_declined: "Kein Problem. Ich leite dich an den Fahrer weiter.",
		sms_sent: "Wir haben soeben eine SMS mit dem Link versendet. Bitte öffne den Link und teile uns deinen Standort mit. Wir rufen dich anschließend zurück.",
		sms_text: "Hier ist die Notdienststation.\nTeile deinen Standort mit diesem Link: {location_link}",
		price_quote: "Die Kosten betragen {price_words} Euro und die Wartezeit beträgt {duration_str}. Möchtest du jetzt verbunden werden?",
		yes_no_prompt: "Bitte sage ja oder nein.",
		transfer_message: "Ich verbinde dich mit einem Mitarbeiter.",
		goodbye: "Vielen Dank für deinen Anruf. Wir wünschen dir noch einen schönen Tag.",
		all_busy: "Leider sind alle unsere Mitarbeiter im Gespräch. Bitte rufe später erneut an.",
		no_input: "Leider konnte ich keine Eingabe erkennen. Ich verbinde dich mit einem Mitarbeiter.",
		outbound_greeting: "Hier ist die Notdienststation. Wir haben deinen Standort erhalten. Der Preis für den {service_name} beträgt {price} Euro. Die Ankunftszeit beträgt ungefähr {duration} Minuten. Möchtest du den {service_name} jetzt beauftragen?",
		outbound_yes_no: "Bitte sagen Sie Ja oder Nein.",
		driver_sms: "Anrufdetails:\nAnrufer: {caller}\nAdresse: {address}\nPreis: {price} Euro\nWartezeit: {duration} min\n{maps_link}",
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
			title: "Begrüßung & Absicht",
			icon: MessageCircleIcon,
			color: "text-sky-600",
			bgGradient: "from-sky-50 to-blue-50",
			borderColor: "border-sky-200",
			dotColor: "bg-sky-500",
			badgeColor: "bg-sky-100 text-sky-700",
			nodes: [
				{ key: "greeting", label: "Begrüßung", description: "Erste Ansage beim Anruf", placeholders: [] },
				{ key: "intent_prompt", label: "Absicht erfragen", description: "Aufforderung das Anliegen zu beschreiben", placeholders: [] },
				{ key: "intent_not_understood", label: "Nicht verstanden", description: "Wenn die Absicht nicht erkannt wurde", placeholders: [] },
				{ key: "intent_failed", label: "Fehlgeschlagen", description: "Nach mehrfachem Nicht-Verstehen", placeholders: [] },
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
				{ key: "zipcode_request", label: "PLZ erfragen", description: "Postleitzahl über Nummernblock anfordern", placeholders: [] },
			],
		},
		{
			id: 3,
			title: "SMS-Standort",
			icon: SmartphoneIcon,
			color: "text-violet-600",
			bgGradient: "from-violet-50 to-purple-50",
			borderColor: "border-violet-200",
			dotColor: "bg-violet-500",
			badgeColor: "bg-violet-100 text-violet-700",
			nodes: [
				{ key: "sms_offer", label: "SMS anbieten", description: "Standort-Link per SMS vorschlagen", placeholders: [] },
				{ key: "sms_confirm_prompt", label: "SMS bestätigen", description: "Nachfrage ob SMS gewünscht", placeholders: [] },
				{ key: "sms_declined", label: "SMS abgelehnt", description: "Wenn Kunde SMS nicht möchte", placeholders: [] },
				{ key: "sms_sent", label: "SMS versendet", description: "Bestätigung dass SMS gesendet wurde", placeholders: [] },
				{ key: "sms_text", label: "SMS-Text", description: "Inhalt der versendeten SMS", placeholders: ["{location_link}"] },
			],
			branchAfter: "sms_confirm_prompt",
		},
		{
			id: 4,
			title: "Preise & Bestätigung",
			icon: ReceiptIcon,
			color: "text-emerald-600",
			bgGradient: "from-emerald-50 to-green-50",
			borderColor: "border-emerald-200",
			dotColor: "bg-emerald-500",
			badgeColor: "bg-emerald-100 text-emerald-700",
			nodes: [
				{ key: "price_quote", label: "Preisansage", description: "Kosten und Wartezeit nennen", placeholders: ["{price_words}", "{duration_str}"] },
				{ key: "yes_no_prompt", label: "Ja/Nein Abfrage", description: "Aufforderung zur Bestätigung", placeholders: [] },
			],
		},
		{
			id: 5,
			title: "Weiterleitung & Ende",
			icon: PhoneForwardedIcon,
			color: "text-slate-600",
			bgGradient: "from-slate-50 to-gray-50",
			borderColor: "border-slate-200",
			dotColor: "bg-slate-500",
			badgeColor: "bg-slate-100 text-slate-700",
			nodes: [
				{ key: "transfer_message", label: "Verbindung", description: "Ankündigung der Weiterleitung", placeholders: [] },
				{ key: "goodbye", label: "Verabschiedung", description: "Abschluss des Gesprächs", placeholders: [] },
				{ key: "all_busy", label: "Alle besetzt", description: "Wenn kein Mitarbeiter verfügbar ist", placeholders: [] },
			],
		},
		{
			id: 6,
			title: "Fehlerbehandlung",
			icon: AlertTriangleIcon,
			color: "text-red-600",
			bgGradient: "from-red-50 to-rose-50",
			borderColor: "border-red-200",
			dotColor: "bg-red-500",
			badgeColor: "bg-red-100 text-red-700",
			nodes: [
				{ key: "no_input", label: "Keine Eingabe", description: "Wenn keine Spracheingabe erkannt wurde", placeholders: [] },
			],
		},
		{
			id: 7,
			title: "Rückruf",
			icon: PhoneOutgoingIcon,
			color: "text-cyan-600",
			bgGradient: "from-cyan-50 to-teal-50",
			borderColor: "border-cyan-200",
			dotColor: "bg-cyan-500",
			badgeColor: "bg-cyan-100 text-cyan-700",
			nodes: [
				{ key: "outbound_greeting", label: "Rückruf-Begrüßung", description: "Ansage beim ausgehenden Rückruf", placeholders: ["{service_name}", "{price}", "{duration}"] },
				{ key: "outbound_yes_no", label: "Ja/Nein Abfrage", description: "Bestätigung beim Rückruf erfragen", placeholders: [] },
			],
		},
		{
			id: 8,
			title: "SMS an Fahrer",
			icon: SendIcon,
			color: "text-orange-600",
			bgGradient: "from-orange-50 to-amber-50",
			borderColor: "border-orange-200",
			dotColor: "bg-orange-500",
			badgeColor: "bg-orange-100 text-orange-700",
			nodes: [
				{ key: "driver_sms", label: "Fahrer-SMS", description: "SMS mit Auftragsdetails an den Fahrer", placeholders: ["{caller}", "{address}", "{price}", "{duration}", "{maps_link}"] },
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
								{#each phase.nodes as node, nodeIdx}
									{@const isBranchPoint = phase.branchAfter === node.key}

									{#if isBranchPoint}
										<!-- Branch point node -->
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

										<!-- Branch fork visualization -->
										<div>
											<div class="flex items-center gap-2 text-xs text-muted-foreground mb-2">
												<div class="h-px flex-1 bg-muted-foreground/20"></div>
												<span class="font-medium">Verzweigung</span>
												<div class="h-px flex-1 bg-muted-foreground/20"></div>
											</div>
											<div class="grid grid-cols-2 gap-3">
												<!-- "Nein" branch -->
												<div class="rounded-lg border border-red-200 bg-red-50/50 p-3">
													<div class="flex items-center gap-1.5 mb-2">
														<span class="inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-bold bg-red-100 text-red-700">NEIN</span>
														<span class="font-medium text-sm">SMS abgelehnt</span>
													</div>
													<textarea
														class="w-full rounded-md border border-input bg-white px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-y min-h-[60px]"
														rows="2"
														bind:value={announcements.sms_declined}
													></textarea>
												</div>
												<!-- "Ja" branch -->
												<div class="rounded-lg border border-green-200 bg-green-50/50 p-3 space-y-3">
													<div class="flex items-center gap-1.5 mb-2">
														<span class="inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-bold bg-green-100 text-green-700">JA</span>
														<span class="font-medium text-sm">SMS versenden</span>
													</div>
													<div>
														<span class="text-xs text-muted-foreground">SMS versendet</span>
														<textarea
															class="w-full rounded-md border border-input bg-white px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-y min-h-[60px]"
															rows="2"
															bind:value={announcements.sms_sent}
														></textarea>
													</div>
													<div>
														<span class="text-xs text-muted-foreground">SMS-Text</span>
														<textarea
															class="w-full rounded-md border border-input bg-white px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring resize-y min-h-[60px]"
															rows="2"
															bind:value={announcements.sms_text}
														></textarea>
														<div class="flex flex-wrap gap-1 mt-1">
															<span class="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-mono font-medium bg-violet-100 text-violet-700 border border-violet-200">{"{location_link}"}</span>
														</div>
													</div>
												</div>
											</div>
										</div>

									{:else if phase.branchAfter && (node.key === "sms_declined" || node.key === "sms_sent" || node.key === "sms_text")}
										<!-- Skip — rendered in branch above -->

									{:else}
										<!-- Standard node -->
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
									{/if}
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
