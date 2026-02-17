<script lang="ts">
	import * as Dialog from "$lib/components/ui/dialog/index.js";
	import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
	import { Button } from "$lib/components/ui/button/index.js";
	import { Input } from "$lib/components/ui/input/index.js";
	import { Label } from "$lib/components/ui/label/index.js";
	import { Skeleton } from "$lib/components/ui/skeleton/index.js";
	import type { Kontakt, ServiceId } from "$lib/types";
	import {
		getKontakte,
		createKontakt,
		updateKontakt,
		deleteKontakt,
		geocodeAddress,
	} from "$lib/api";

	let {
		contactId = null,
		isNew = false,
		open = $bindable(true),
		serviceId,
		onclose,
		onsave,
	}: {
		contactId?: string | null;
		isNew?: boolean;
		open?: boolean;
		serviceId: ServiceId;
		onclose?: () => void;
		onsave?: () => void;
	} = $props();

	let contact = $state<Kontakt | null>(null);
	let loading = $state(false);
	let saving = $state(false);
	let error = $state("");
	let deleteConfirmOpen = $state(false);

	// Form state
	let name = $state("");
	let phone = $state("");
	let address = $state("");
	let zipcode = $state("");

	// Original values to detect changes
	let originalAddress = $state("");
	let originalZipcode = $state("");

	async function loadContact() {
		if (!contactId || isNew) {
			// New contact — reset form
			name = "";
			phone = "";
			address = "";
			zipcode = "";
			originalAddress = "";
			originalZipcode = "";
			contact = null;
			return;
		}

		loading = true;
		error = "";
		try {
			const all = await getKontakte(serviceId);
			const found = all.find((c) => c.id === contactId);
			if (found) {
				contact = found;
				name = contact.name;
				phone = contact.phone || "";
				address = contact.address || "";
				zipcode = String(contact.zipcode || "");
				originalAddress = contact.address || "";
				originalZipcode = String(contact.zipcode || "");
			} else {
				error = "Kontakt nicht gefunden";
			}
		} catch (e) {
			error = e instanceof Error ? e.message : "Ein unbekannter Fehler ist aufgetreten.";
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		if (open) {
			loadContact();
		}
	});

	async function handleSave() {
		if (!name.trim()) {
			error = "Name ist erforderlich";
			return;
		}

		saving = true;
		error = "";

		try {
			// Re-geocode if address or zipcode changed, or if no coordinates yet
			let latitude = contact?.latitude;
			let longitude = contact?.longitude;

			const geocodeQuery = [address, zipcode].filter(Boolean).join(", ");
			const addressChanged = address !== originalAddress || zipcode !== originalZipcode;
			const hasCoords = latitude != null && longitude != null;

			if ((addressChanged || !hasCoords) && geocodeQuery.length > 2) {
				try {
					const geo = await geocodeAddress(geocodeQuery);
					latitude = geo.latitude;
					longitude = geo.longitude;
				} catch {
					// Geocoding failed, keep old coords
				}
			}

			const payload = {
				name,
				phone,
				address,
				zipcode,
				latitude,
				longitude,
			};

			if (isNew) {
				await createKontakt(serviceId, payload);
			} else if (contactId) {
				await updateKontakt(serviceId, contactId, payload);
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
		if (!contactId) return;
		try {
			await deleteKontakt(serviceId, contactId);
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

	const title = $derived(isNew ? "Neuer Kontakt" : (name || "Kontakt"));
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
						{isNew ? "Neuen Kontakt anlegen" : "Kontakt bearbeiten"}
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

				<!-- Form fields -->
				<div class="grid gap-4">
					<div class="grid gap-2">
						<Label for="contact-name">Name *</Label>
						<Input id="contact-name" bind:value={name} placeholder="Name des Kontakts" />
					</div>
					<div class="grid gap-2">
						<Label for="contact-phone">Telefonnummer *</Label>
						<Input id="contact-phone" bind:value={phone} placeholder="+49 123 456789" />
					</div>
					<div class="grid gap-2">
						<Label for="contact-address">Adresse (Optional)</Label>
						<Input id="contact-address" bind:value={address} placeholder="Straße, PLZ Ort" />
						<p class="text-xs text-muted-foreground">
							Wird für die Routenberechnung und Karte verwendet
						</p>
					</div>
					<div class="grid gap-2">
						<Label for="contact-zipcode">PLZ (Optional)</Label>
						<Input id="contact-zipcode" bind:value={zipcode} placeholder="87509" />
					</div>
				</div>
			</div>

			<!-- Footer -->
			<div class="sticky bottom-0 bg-background border-t px-4 sm:px-6 py-2.5 sm:py-3 flex items-center gap-2">
				{#if !isNew && contactId}
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
			<AlertDialog.Title>Kontakt löschen</AlertDialog.Title>
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
