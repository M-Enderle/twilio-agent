<script lang="ts">
	import * as Dialog from "$lib/components/ui/dialog/index.js";
	import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
	import { Button } from "$lib/components/ui/button/index.js";
	import { Input } from "$lib/components/ui/input/index.js";
	import { Label } from "$lib/components/ui/label/index.js";
	import { Skeleton } from "$lib/components/ui/skeleton/index.js";
	import type { Standort, StandortKontakt, ServiceId } from "$lib/types";
	import {
		getStandorte,
		createStandort,
		updateStandort,
		deleteStandort,
		geocodeAddress,
	} from "$lib/api";

	let {
		standortId = null,
		isNew = false,
		open = $bindable(true),
		serviceId,
		onclose,
		onsave,
	}: {
		standortId?: string | null;
		isNew?: boolean;
		open?: boolean;
		serviceId: ServiceId;
		onclose?: () => void;
		onsave?: () => void;
	} = $props();

	let standort = $state<Standort | null>(null);
	let loading = $state(false);
	let saving = $state(false);
	let error = $state("");
	let deleteConfirmOpen = $state(false);

	// Form state
	let name = $state("");
	let address = $state("");
	let contacts = $state<StandortKontakt[]>([]);

	// Original values to detect changes
	let originalAddress = $state("");

	async function loadStandort() {
		if (!standortId || isNew) {
			// New location — reset form
			name = "";
			address = "";
			contacts = [];
			originalAddress = "";
			standort = null;
			return;
		}

		loading = true;
		error = "";
		try {
			const all = await getStandorte(serviceId);
			const found = all.find((s) => s.id === standortId);
			if (found) {
				standort = found;
				name = standort.name;
				address = standort.address || "";
				contacts = JSON.parse(JSON.stringify(standort.contacts || [])); // Deep copy
				originalAddress = standort.address || "";
			} else {
				error = "Standort nicht gefunden";
			}
		} catch (e) {
			error = e instanceof Error ? e.message : "Ein unbekannter Fehler ist aufgetreten.";
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		if (open) {
			loadStandort();
		}
	});

	function addContact() {
		const position = contacts.length;
		contacts = [...contacts, { name: "", phone: "", position }];
	}

	function removeContact(index: number) {
		contacts = contacts.filter((_, i) => i !== index);
		// Re-index positions
		contacts = contacts.map((c, i) => ({ ...c, position: i }));
	}

	function moveContactUp(index: number) {
		if (index === 0) return;
		const newContacts = [...contacts];
		[newContacts[index - 1], newContacts[index]] = [newContacts[index], newContacts[index - 1]];
		// Re-index positions
		contacts = newContacts.map((c, i) => ({ ...c, position: i }));
	}

	function moveContactDown(index: number) {
		if (index === contacts.length - 1) return;
		const newContacts = [...contacts];
		[newContacts[index], newContacts[index + 1]] = [newContacts[index + 1], newContacts[index]];
		// Re-index positions
		contacts = newContacts.map((c, i) => ({ ...c, position: i }));
	}

	async function handleSave() {
		if (!name.trim()) {
			error = "Name ist erforderlich";
			return;
		}

		saving = true;
		error = "";

		try {
			// Re-geocode if address changed, or if no coordinates yet
			let latitude = standort?.latitude;
			let longitude = standort?.longitude;

			const addressChanged = address !== originalAddress;
			const hasCoords = latitude != null && longitude != null;

			if ((addressChanged || !hasCoords) && address.trim().length > 2) {
				try {
					const geo = await geocodeAddress(address);
					latitude = geo.latitude;
					longitude = geo.longitude;
				} catch (geoError) {
					// Geocoding failed, show error to user
					error = "Adresse konnte nicht gefunden werden. Bitte überprüfen Sie die Adresse.";
					saving = false;
					return;
				}
			}

			const data = {
				name,
				address,
				latitude,
				longitude,
				contacts,
			};

			if (isNew) {
				await createStandort(serviceId, data);
			} else if (standortId) {
				await updateStandort(serviceId, standortId, data);
			}

			onsave?.();
			handleClose();
		} catch (e) {
			error = e instanceof Error ? e.message : "Ein unbekannter Fehler ist aufgetreten.";
		} finally {
			saving = false;
		}
	}

	async function handleDelete() {
		if (!standortId) return;
		try {
			await deleteStandort(serviceId, standortId);
			onsave?.();
			handleClose();
		} catch (e) {
			error = e instanceof Error ? e.message : "Ein unbekannter Fehler ist aufgetreten.";
		}
	}

	function handleClose() {
		open = false;
		onclose?.();
	}

	function handleOpenChange(newOpen: boolean) {
		open = newOpen;
		if (!newOpen) {
			onclose?.();
		}
	}

	const title = $derived(isNew ? "Neuer Standort" : (name || "Standort"));
</script>

<Dialog.Root open={open} onOpenChange={handleOpenChange}>
	<Dialog.Content
		class="max-w-[100vw] sm:max-w-2xl max-h-[100dvh] sm:max-h-[90vh] h-[100dvh] sm:h-auto overflow-y-auto p-0 rounded-none sm:rounded-lg gap-0"
		showCloseButton={false}
	>
		<!-- Header -->
		<div class="sticky top-0 z-10 bg-background border-b px-4 sm:px-6 py-3 sm:py-4">
			<div class="flex items-center justify-between gap-2">
				<div class="min-w-0">
					<Dialog.Title class="text-base sm:text-lg font-semibold truncate">
						{title}
					</Dialog.Title>
					<Dialog.Description class="text-xs sm:text-sm text-muted-foreground">
						{isNew ? "Neuen Standort anlegen" : "Standort bearbeiten"}
					</Dialog.Description>
				</div>
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

		{#if loading}
			<div class="p-4 sm:p-6 space-y-4">
				<Skeleton class="h-10 w-full" />
				<Skeleton class="h-10 w-full" />
				<Skeleton class="h-10 w-full" />
				<Skeleton class="h-32 w-full" />
			</div>
		{:else}
			<div class="p-4 sm:p-6 space-y-5 sm:space-y-6">
				{#if error}
					<div class="rounded-lg bg-red-50 border border-red-200 p-3 text-red-800 text-sm">
						{error}
					</div>
				{/if}

				<!-- Location fields -->
				<div class="grid gap-4">
					<div class="grid gap-2">
						<Label for="location-name">Standortname *</Label>
						<Input id="location-name" bind:value={name} placeholder="z.B. Firma XY" />
					</div>
					<div class="grid gap-2">
						<Label for="location-address">Adresse</Label>
						<Input id="location-address" bind:value={address} placeholder="Straße, PLZ Ort" />
						<p class="text-xs text-muted-foreground">
							Wird für die Routenberechnung und Karte verwendet
						</p>
					</div>
				</div>

				<!-- Contacts section -->
				<div class="border-t pt-4">
					<div class="flex items-center justify-between mb-3">
						<Label class="text-base">Kontakte</Label>
						<Button size="sm" variant="outline" onclick={addContact}>
							<svg class="h-4 w-4 mr-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
							</svg>
							Hinzufügen
						</Button>
					</div>

					{#if contacts.length === 0}
						<p class="text-sm text-muted-foreground text-center py-4 border rounded-lg">
							Noch keine Kontakte. Klicke auf "Hinzufügen" um einen Kontakt anzulegen.
						</p>
					{:else}
						<div class="space-y-2">
							{#each contacts as contact, i (i)}
								<div class="border rounded-lg p-3 bg-muted/30">
									<div class="flex items-start gap-2">
										<!-- Position indicator -->
										<div class="flex flex-col gap-1 mt-6">
											<button
												type="button"
												onclick={() => moveContactUp(i)}
												disabled={i === 0}
												class="p-0.5 hover:bg-muted rounded disabled:opacity-30"
												aria-label="Nach oben"
											>
												<svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
													<path stroke-linecap="round" stroke-linejoin="round" d="M5 15l7-7 7 7" />
												</svg>
											</button>
											<span class="text-xs font-mono text-center">{i + 1}</span>
											<button
												type="button"
												onclick={() => moveContactDown(i)}
												disabled={i === contacts.length - 1}
												class="p-0.5 hover:bg-muted rounded disabled:opacity-30"
												aria-label="Nach unten"
											>
												<svg class="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
													<path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
												</svg>
											</button>
										</div>

										<!-- Contact fields -->
										<div class="flex-1 grid gap-2">
											<Input
												bind:value={contact.name}
												placeholder="Name"
												class="text-sm"
											/>
											<Input
												bind:value={contact.phone}
												placeholder="Telefonnummer"
												class="text-sm"
											/>
										</div>

										<!-- Delete button -->
										<button
											type="button"
											onclick={() => removeContact(i)}
											class="mt-6 p-1.5 hover:bg-destructive/10 text-destructive rounded"
											aria-label="Löschen"
										>
											<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
												<path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
											</svg>
										</button>
									</div>
								</div>
							{/each}
						</div>
					{/if}
					<p class="text-xs text-muted-foreground mt-2">
						Die Reihenfolge der Kontakte bestimmt die Anrufreihenfolge bei Weiterleitungen.
					</p>
				</div>
			</div>

			<!-- Footer -->
			<div class="sticky bottom-0 bg-background border-t px-4 sm:px-6 py-2.5 sm:py-3 flex items-center gap-2">
				{#if !isNew && standortId}
					<Button
						variant="destructive"
						size="sm"
						onclick={() => { deleteConfirmOpen = true; }}
					>
						Löschen
					</Button>
				{/if}
				<div class="flex-1"></div>
				<Button variant="outline" size="sm" onclick={() => handleOpenChange(false)}>
					Abbrechen
				</Button>
				<Button size="sm" onclick={handleSave} disabled={saving}>
					{saving ? "Speichern..." : (isNew ? "Erstellen" : "Speichern")}
				</Button>
			</div>
		{/if}
	</Dialog.Content>
</Dialog.Root>

<!-- Delete Confirmation -->
<AlertDialog.Root bind:open={deleteConfirmOpen}>
	<AlertDialog.Content>
		<AlertDialog.Header>
			<AlertDialog.Title>Standort löschen</AlertDialog.Title>
			<AlertDialog.Description>
				Möchtest du <strong>{name}</strong> wirklich löschen? Diese Aktion
				kann nicht rückgängig gemacht werden.
			</AlertDialog.Description>
		</AlertDialog.Header>
		<AlertDialog.Footer>
			<AlertDialog.Cancel>Abbrechen</AlertDialog.Cancel>
			<AlertDialog.Action
				onclick={handleDelete}
				class="bg-destructive text-white hover:bg-destructive/90"
			>
				Löschen
			</AlertDialog.Action>
		</AlertDialog.Footer>
	</AlertDialog.Content>
</AlertDialog.Root>
