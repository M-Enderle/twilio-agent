<script lang="ts">
	import * as Dialog from "$lib/components/ui/dialog/index.js";
	import { Badge } from "$lib/components/ui/badge/index.js";
	import { Button } from "$lib/components/ui/button/index.js";
	import { Skeleton } from "$lib/components/ui/skeleton/index.js";
	import PhoneIcon from "@lucide/svelte/icons/phone";
	import InfoIcon from "@lucide/svelte/icons/info";
	import MicIcon from "@lucide/svelte/icons/mic";
	import MessageCircleIcon from "@lucide/svelte/icons/message-circle";
	import { getCallDetail, getRecordingUrl } from "$lib/api";
	import { formatPhone } from "$lib/utils";
	import type { CallDetail, CallMessage, RecordingInfo } from "$lib/types";

	let {
		number,
		timestamp,
		open = $bindable(true),
		onclose,
	}: {
		number: string;
		timestamp: string;
		open?: boolean;
		onclose?: () => void;
	} = $props();

	let detail = $state<CallDetail | null>(null);
	let error = $state("");
	let audioUrls = $state<Record<string, string>>({});
	let loadedRecordings = $state<Set<string>>(new Set());

	const EXCLUDED_KEYS = new Set([
		"call_number",
		"PLZ",
		"Ort",
		"hangup_reason",
		"Live",
		"Anbieter",
		"Service",
		"Audioaufnahme",
		"Audioaufnahme (Erstanruf)",
		"Audioaufnahme (SMS Rückruf)",
		"Warteschlange",
	]);

	async function loadDetail() {
		try {
			const result = await getCallDetail(number, timestamp);
			detail = result;
			error = "";
		} catch (e) {
			error = e instanceof Error ? e.message : "Ein unbekannter Fehler ist aufgetreten.";
		}
	}

	function loadAudio() {
		if (!detail) return;

		// Only load recordings that haven't been loaded yet
		const newRecordings = Object.keys(detail.recordings).filter(
			recType => !loadedRecordings.has(recType)
		);

		if (newRecordings.length === 0) return;

		// Create URLs only for new recordings
		const newUrls: Record<string, string> = {};
		for (const recType of newRecordings) {
			newUrls[recType] = getRecordingUrl(number, timestamp, recType);
			loadedRecordings.add(recType);
		}

		// Merge new URLs with existing ones
		audioUrls = { ...audioUrls, ...newUrls };
	}

	function cleanup() {
		audioUrls = {};
		loadedRecordings = new Set();
		detail = null;
	}

	$effect(() => {
		if (!open) {
			cleanup();
			return;
		}
		loadDetail();
		const interval = setInterval(loadDetail, 2000);
		return () => clearInterval(interval);
	});

	$effect(() => {
		if (detail && Object.keys(detail.recordings).length > 0) {
			loadAudio();
		}
	});

	function handleOpenChange(newOpen: boolean) {
		open = newOpen;
		if (!newOpen) {
			onclose?.();
		}
	}

	const infoEntries = $derived(
		detail
			? Object.entries(detail.info).filter(([key]) => !EXCLUDED_KEYS.has(key))
			: []
	);

	const isLive = $derived(
		detail?.info?.Live === true ||
		detail?.info?.Live === "true" ||
		detail?.info?.Live === "Ja"
	);
	const hangupReason = $derived(detail?.info?.hangup_reason ?? "");
	const phone = $derived(detail?.info?.Telefonnummer ?? detail?.info?.Anrufnummer ?? number);

	const queue = $derived.by(() => {
		const queueData = detail?.info?.Warteschlange;
		if (!queueData) return [];
		// Handle both array of objects and array of strings (legacy)
		if (Array.isArray(queueData)) {
			return queueData.map((item, index) => {
				if (typeof item === "string") {
					return { name: item, phone: "", position: index + 1 };
				}
				return { ...item, position: index + 1 };
			});
		}
		return [];
	});

	function formatValue(key: string, value: any): string {
		if (key === "Startzeit" && value) {
			try {
				return new Date(value).toLocaleDateString("de-DE", {
					year: "numeric",
					month: "long",
					day: "numeric",
					hour: "2-digit",
					minute: "2-digit",
					second: "2-digit",
					timeZoneName: "short",
				});
			} catch {
				return String(value);
			}
		}
		if (key === "Preis" && value) return `${value}`;
		if (key === "Wartezeit" && value) return `${value} Min`;
		if (Array.isArray(value)) return value.join(", ");
		if (value != null) return String(value);
		return "";
	}

	function isUrl(value: string): boolean {
		return typeof value === "string" && (value.startsWith("http://") || value.startsWith("https://"));
	}

	function isLocation(key: string, value: any): boolean {
		return key === "Standort" && value != null;
	}

	function formatLocation(value: any): { text: string; href?: string } {
		if (typeof value === "object" && value !== null) {
			const address = value.formatted_address || value.google_maps_link || "";
			if (value.google_maps_link) return { text: address, href: value.google_maps_link };
			return { text: address || "Nicht verfügbar" };
		}
		if (typeof value === "string" && value.includes(",")) {
			const parts = value.split(",");
			const lat = parts[0]?.trim();
			const lng = parts[1]?.trim();
			if (lat && lng) {
				return {
					text: "Koordinaten anzeigen",
					href: `https://maps.google.com/?q=${encodeURIComponent(`${lat},${lng}`)}`,
				};
			}
		}
		return { text: String(value) };
	}

	function getRoleLabel(msg: CallMessage): string {
		const model = msg.model?.toLowerCase() ?? "";
		const role = msg.role_class;
		if (role === "user") return "";
		if (model.includes("grok")) return "Grok";
		if (model.includes("gpt")) return "GPT";
		if (model.includes("google")) return "Google";
		if (role === "ai" && model) return model.charAt(0).toUpperCase() + model.slice(1);
		if (role === "ai") return "KI";
		if (role === "cache") return "Cache";
		if (role === "twilio") return "Twilio";
		return "";
	}

	function getMessageClasses(msg: CallMessage): { bubble: string; align: string; isSystem: boolean } {
		const roleClass = msg.model ? msg.model.toLowerCase() : msg.role_class;

		if (roleClass.includes("user")) {
			return { bubble: "bg-blue-600 text-white", align: "justify-end", isSystem: false };
		}
		if (roleClass.includes("assistant")) {
			return { bubble: "bg-muted text-foreground", align: "justify-start", isSystem: false };
		}
		if (roleClass.includes("grok")) {
			return { bubble: "bg-violet-50 text-violet-900 border border-violet-200", align: "justify-start", isSystem: true };
		}
		if (roleClass.includes("gpt")) {
			return { bubble: "bg-emerald-50 text-emerald-900 border border-emerald-200", align: "justify-start", isSystem: true };
		}
		if (roleClass.includes("cache")) {
			return { bubble: "bg-amber-50 text-amber-900 border border-amber-200", align: "justify-start", isSystem: true };
		}
		if (roleClass.includes("google")) {
			return { bubble: "bg-sky-50 text-sky-900 border border-sky-200", align: "justify-start", isSystem: true };
		}
		if (roleClass.includes("twilio")) {
			return { bubble: "bg-orange-50 text-orange-900 border border-orange-200", align: "justify-start", isSystem: true };
		}
		if (roleClass.includes("ai")) {
			return { bubble: "bg-slate-50 text-slate-700 border border-slate-200", align: "justify-start", isSystem: true };
		}
		return { bubble: "bg-muted text-foreground", align: "justify-start", isSystem: false };
	}

	function getRecordingLabel(recType: string): string {
		const labels: Record<string, string> = {
			initial: "Erstanruf",
			followup: "SMS-Rückruf",
		};
		return labels[recType] || recType;
	}

	function formatDuration(seconds: number): string {
		const mins = Math.floor(seconds / 60);
		const secs = seconds % 60;
		if (mins > 0) {
			return `${mins}:${secs.toString().padStart(2, "0")} min`;
		}
		return `${secs}s`;
	}

	async function downloadRecording(recType: string) {
		const url = audioUrls[recType];
		if (!url) return;

		try {
			const response = await fetch(url);
			const blob = await response.blob();
			const blobUrl = URL.createObjectURL(blob);

			const a = document.createElement("a");
			a.href = blobUrl;
			a.download = `recording-${phone}-${recType}-${new Date().toISOString().split("T")[0]}.mp3`;
			document.body.appendChild(a);
			a.click();
			document.body.removeChild(a);

			// Clean up blob URL
			setTimeout(() => URL.revokeObjectURL(blobUrl), 100);
		} catch (err) {
			console.error("Download failed:", err);
		}
	}

</script>

<Dialog.Root open={open} onOpenChange={handleOpenChange}>
	<Dialog.Content
		class="max-w-[100vw] sm:max-w-3xl max-h-[100dvh] sm:max-h-[90vh] h-[100dvh] sm:h-auto overflow-y-auto p-0 rounded-none sm:rounded-lg gap-0"
		showCloseButton={false}
	>
		{#if error}
			<div class="rounded-lg bg-red-50 border border-red-200 p-3 m-4 sm:m-6 text-red-800 text-sm">
				{error}
			</div>
		{:else if !detail}
			<div class="p-4 sm:p-6 space-y-4">
				<Dialog.Header>
					<Dialog.Title>Anrufdetails</Dialog.Title>
					<Dialog.Description>Lade Anrufdetails...</Dialog.Description>
				</Dialog.Header>
				<div class="space-y-3">
					<Skeleton class="h-16 sm:h-20 w-full rounded-lg" />
					<Skeleton class="h-40 sm:h-48 w-full rounded-lg" />
				</div>
			</div>
		{:else}
			<!-- Header bar -->
			<div class="sticky top-0 z-10 bg-background border-b px-4 sm:px-6 py-3 sm:py-4">
				<div class="flex items-center justify-between gap-2">
					<div class="flex items-center gap-2.5 sm:gap-3 min-w-0">
						<div class="flex items-center justify-center w-9 h-9 sm:w-10 sm:h-10 rounded-full shrink-0 {isLive ? 'bg-green-100' : 'bg-slate-100'}">
							<PhoneIcon class="h-4 w-4 sm:h-5 sm:w-5 {isLive ? 'text-green-600' : 'text-slate-500'}" />
						</div>
						<div class="min-w-0">
							<Dialog.Title class="text-base sm:text-lg font-semibold truncate">
								{formatPhone(phone)}
							</Dialog.Title>
							<Dialog.Description class="text-xs sm:text-sm text-muted-foreground truncate">
								{detail.info.Anbieter ?? ""}{detail.info.Service ? ` \u2022 ${detail.info.Service}` : ""}
							</Dialog.Description>
						</div>
					</div>
					<div class="flex items-center gap-2 shrink-0">
						{#if isLive}
							<Badge class="bg-green-100 text-green-700 border-green-200 gap-1.5 text-xs">
								<span class="relative flex h-2 w-2">
									<span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-500 opacity-75"></span>
									<span class="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
								</span>
								Live
							</Badge>
						{:else}
							<Badge variant="secondary" class="text-muted-foreground text-xs">
								Beendet
							</Badge>
						{/if}
						<button
							class="rounded-full p-1.5 hover:bg-muted transition-colors sm:hidden"
							onclick={() => handleOpenChange(false)}
							aria-label="Schließen"
						>
							<svg class="h-5 w-5 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
							</svg>
						</button>
					</div>
				</div>
			</div>

			<div class="p-4 sm:p-6 space-y-5 sm:space-y-6 flex-1">
				<!-- Call Info -->
				{#if infoEntries.length > 0}
					<div>
						<h3 class="text-xs sm:text-sm font-medium text-muted-foreground mb-2.5 sm:mb-3 flex items-center gap-2">
							<InfoIcon class="h-3.5 w-3.5 sm:h-4 sm:w-4" />
							Anrufdetails
						</h3>
						<div class="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-3">
							{#each infoEntries as [key, value]}
								<div class="min-w-0">
									<p class="text-[11px] sm:text-xs text-muted-foreground mb-0.5">{key}</p>
									{#if isLocation(key, value)}
										{@const loc = formatLocation(value)}
										{#if loc.href}
											<a
												href={loc.href}
												target="_blank"
												rel="noopener noreferrer"
												class="text-xs sm:text-sm font-medium text-blue-600 hover:underline break-words"
											>
												{loc.text}
											</a>
										{:else}
											<p class="text-xs sm:text-sm font-medium break-words">{loc.text}</p>
										{/if}
									{:else if isUrl(formatValue(key, value))}
										<a
											href={formatValue(key, value)}
											target="_blank"
											rel="noopener noreferrer"
											class="text-xs sm:text-sm font-medium text-blue-600 hover:underline truncate block"
										>
											Link
										</a>
									{:else}
										<p class="text-xs sm:text-sm font-medium break-words">{formatValue(key, value)}</p>
									{/if}
								</div>
							{/each}
						</div>
					</div>
				{/if}

				<!-- Contact Queue -->
				{#if queue.length > 0}
					<div>
						<h3 class="text-xs sm:text-sm font-medium text-muted-foreground mb-2.5 sm:mb-3 flex items-center gap-2">
							<svg class="h-3.5 w-3.5 sm:h-4 sm:w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
							</svg>
							Anrufwarteschlange
						</h3>
						<div class="space-y-2">
							{#each queue as contact, index}
								<div class="group relative rounded-lg border bg-gradient-to-r from-muted/40 to-muted/20 hover:from-muted/60 hover:to-muted/40 transition-all duration-200">
									<div class="flex items-center gap-3 p-3 sm:p-3.5">
										<!-- Position Badge -->
										<div class="flex items-center justify-center w-7 h-7 sm:w-8 sm:h-8 rounded-full bg-primary/10 text-primary font-semibold text-xs sm:text-sm shrink-0 ring-2 ring-primary/20">
											{contact.position}
										</div>

										<!-- Contact Info -->
										<div class="flex-1 min-w-0">
											<div class="flex items-center gap-2">
												<p class="text-xs sm:text-sm font-semibold text-foreground truncate">
													{contact.name || "Unbekannt"}
												</p>
												{#if index === 0}
													<span class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-green-100 text-green-700 border border-green-200">
														<svg class="w-2.5 h-2.5" fill="currentColor" viewBox="0 0 20 20">
															<path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd" />
														</svg>
														Nächster
													</span>
												{/if}
											</div>
											{#if contact.phone}
												<a
													href="tel:{contact.phone}"
													class="text-[11px] sm:text-xs text-muted-foreground hover:text-blue-600 transition-colors inline-flex items-center gap-1 mt-0.5"
												>
													<svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
														<path stroke-linecap="round" stroke-linejoin="round" d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
													</svg>
													{formatPhone(contact.phone)}
												</a>
											{/if}
										</div>

										<!-- Connection Arrow (except for last item) -->
										{#if index < queue.length - 1}
											<div class="absolute -bottom-2 left-1/2 -translate-x-1/2 z-10">
												<svg class="w-4 h-4 text-muted-foreground/40" fill="currentColor" viewBox="0 0 20 20">
													<path fill-rule="evenodd" d="M10 3a1 1 0 011 1v10.586l2.293-2.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 111.414-1.414L9 14.586V4a1 1 0 011-1z" clip-rule="evenodd" />
												</svg>
											</div>
										{/if}
									</div>
								</div>
							{/each}
						</div>
					</div>
				{/if}

				<!-- Audio Players -->
				{#if Object.keys(detail.recordings).length > 0}
					<div>
						<h3 class="text-xs sm:text-sm font-medium text-muted-foreground mb-2.5 sm:mb-3 flex items-center gap-2">
							<MicIcon class="h-3.5 w-3.5 sm:h-4 sm:w-4" />
							Aufnahmen ({Object.keys(detail.recordings).length})
						</h3>
						<div class="space-y-2.5 sm:space-y-3">
							{#each Object.entries(detail.recordings) as [recType, rec] (recType)}
								<div class="rounded-lg border bg-gradient-to-br from-muted/40 to-muted/20 p-3 sm:p-4 hover:from-muted/60 hover:to-muted/30 transition-all duration-200">
									<div class="flex items-center justify-between mb-2.5">
										<div class="flex items-center gap-2">
											<div class="flex items-center justify-center w-6 h-6 sm:w-7 sm:h-7 rounded-full bg-primary/10 shrink-0">
												<svg class="w-3 h-3 sm:w-3.5 sm:h-3.5 text-primary" fill="currentColor" viewBox="0 0 20 20">
													<path fill-rule="evenodd" d="M7 4a3 3 0 016 0v4a3 3 0 11-6 0V4zm4 10.93A7.001 7.001 0 0017 8a1 1 0 10-2 0A5 5 0 015 8a1 1 0 00-2 0 7.001 7.001 0 006 6.93V17H6a1 1 0 100 2h8a1 1 0 100-2h-3v-2.07z" clip-rule="evenodd" />
												</svg>
											</div>
											<span class="text-xs sm:text-sm font-semibold">{getRecordingLabel(recType)}</span>
										</div>
										<div class="flex items-center gap-2">
											{#if rec.metadata?.duration_total_seconds}
												<span class="text-[10px] sm:text-xs text-muted-foreground font-medium px-2 py-0.5 rounded-full bg-muted/50">
													{formatDuration(Math.round(rec.metadata.duration_total_seconds))}
												</span>
											{/if}
											{#if audioUrls[recType]}
												<button
													onclick={() => downloadRecording(recType)}
													class="p-1.5 rounded-full hover:bg-muted transition-colors"
													title="Aufnahme herunterladen"
												>
													<svg class="w-3.5 h-3.5 sm:w-4 sm:h-4 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
														<path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
													</svg>
												</button>
											{/if}
										</div>
									</div>

									<!-- Simple Audio Player -->
									{#if audioUrls[recType]}
										<audio
											controls
											preload="metadata"
											class="w-full h-10 sm:h-12 rounded-lg"
											src={audioUrls[recType]}
										>
											<track kind="captions" />
										</audio>
									{:else}
										<Skeleton class="h-10 sm:h-12 w-full rounded-lg" />
									{/if}

									{#if rec.metadata?.bytes_total}
										<div class="flex items-center gap-1 mt-2 text-[10px] sm:text-xs text-muted-foreground">
											<svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
												<path stroke-linecap="round" stroke-linejoin="round" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
											</svg>
											<span>{(rec.metadata.bytes_total / 1024).toFixed(1)} KB</span>
										</div>
									{/if}
								</div>
							{/each}
						</div>
					</div>
				{/if}

				<!-- Chat Transcript -->
				{#if detail.messages.length > 0}
					<div>
						<h3 class="text-xs sm:text-sm font-medium text-muted-foreground mb-2.5 sm:mb-3 flex items-center gap-2">
							<MessageCircleIcon class="h-3.5 w-3.5 sm:h-4 sm:w-4" />
							Gesprächsverlauf
						</h3>
						<div class="rounded-lg border bg-muted/20 p-3 sm:p-4">
							<div class="flex flex-col gap-2.5 sm:gap-3">
								{#each detail.messages as msg}
									{@const classes = getMessageClasses(msg)}
									{@const roleLabel = getRoleLabel(msg)}
									<div class="flex {classes.align}">
										<div class="max-w-[88%] sm:max-w-[80%]">
											{#if roleLabel}
												<p class="text-[10px] font-medium text-muted-foreground mb-0.5 {classes.align === 'justify-end' ? 'text-right' : ''}">
													{roleLabel}
												</p>
											{/if}
											<div class="rounded-2xl px-3 sm:px-4 py-2 sm:py-2.5 text-xs sm:text-sm leading-relaxed {classes.bubble}">
												<span class="whitespace-pre-wrap break-words">{msg.content}</span>
											</div>
										</div>
									</div>
								{/each}
							</div>
						</div>
					</div>
				{/if}

				<!-- Hangup Reason -->
				{#if hangupReason}
					<div class="flex items-center justify-center py-1 sm:py-2">
						<div class="flex items-center gap-2 text-xs sm:text-sm text-muted-foreground">
							<div class="h-px w-6 sm:w-8 bg-border"></div>
							<span>{hangupReason}</span>
							<div class="h-px w-6 sm:w-8 bg-border"></div>
						</div>
					</div>
				{/if}
			</div>

			<!-- Footer -->
			<div class="sticky bottom-0 bg-background border-t px-4 sm:px-6 py-2.5 sm:py-3 flex justify-end">
				<Button variant="outline" size="sm" onclick={() => handleOpenChange(false)}>
					Schließen
				</Button>
			</div>
		{/if}
	</Dialog.Content>
</Dialog.Root>
