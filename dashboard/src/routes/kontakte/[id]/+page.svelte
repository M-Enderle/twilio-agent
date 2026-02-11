<script lang="ts">
	import { page } from "$app/stores";
	import { goto } from "$app/navigation";
	import { onMount } from "svelte";
	import type {
		Contact,
		ContactWithCoords,
		Category,
		FallbackContact,
	} from "$lib/types";
	import {
		getContacts,
		updateContact,
		deleteContact,
		geocodeAddress,
	} from "$lib/api";
	import * as Card from "$lib/components/ui/card/index.js";
	import { Button } from "$lib/components/ui/button/index.js";
	import { Input } from "$lib/components/ui/input/index.js";
	import { Label } from "$lib/components/ui/label/index.js";
	import FallbackList from "$lib/components/FallbackList.svelte";
	import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";

	let contact = $state<ContactWithCoords | null>(null);
	let category = $state<Category>("locksmith");
	let loading = $state(true);
	let saving = $state(false);
	let error = $state("");
	let success = $state("");
	let deleteConfirmOpen = $state(false);

	// Form state
	let name = $state("");
	let phone = $state("");
	let address = $state("");
	let zipcode = $state("");
	let fallbacks = $state<FallbackContact[]>([]);

	// Original values to detect changes
	let originalAddress = $state("");

	const contactId = $derived($page.params.id || "");

	async function loadContact() {
		try {
			const all = await getContacts();
			// Find contact by ID across categories
			for (const cat of ["locksmith", "towing"] as Category[]) {
				const found = all[cat]?.find((c) => c.id === contactId);
				if (found) {
					contact = {
						...found,
						fallbacks: found.fallbacks_json
							? JSON.parse(found.fallbacks_json)
							: [],
					};
					category = cat;
					// Populate form
					name = contact.name;
					phone = contact.phone;
					address = contact.address || "";
					zipcode = String(contact.zipcode || "");
					fallbacks = contact.fallbacks || [];
					originalAddress = contact.address || "";
					break;
				}
			}
			if (!contact) {
				error = "Kontakt nicht gefunden";
			}
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	onMount(loadContact);

	async function handleSave() {
		if (!contact) return;
		saving = true;
		error = "";
		success = "";

		try {
			// Re-geocode if address changed
			let latitude = contact.latitude;
			let longitude = contact.longitude;

			const fullAddress = `${address}, ${zipcode}`.trim();
			if (address !== originalAddress && fullAddress.length > 2) {
				try {
					const geo = await geocodeAddress(fullAddress);
					latitude = geo.latitude;
					longitude = geo.longitude;
				} catch {
					// Geocoding failed, keep old coords
				}
			}

			await updateContact(category, contact.id, {
				name,
				phone,
				address,
				zipcode,
				latitude,
				longitude,
				fallbacks_json: JSON.stringify(fallbacks),
			});

			success = "Kontakt gespeichert";
			originalAddress = address;

			// Update local contact state
			contact = {
				...contact,
				name,
				phone,
				address,
				zipcode,
				latitude,
				longitude,
				fallbacks,
			};

			setTimeout(() => {
				success = "";
			}, 3000);
		} catch (e: any) {
			error = e.message;
		} finally {
			saving = false;
		}
	}

	async function handleDelete() {
		if (!contact) return;
		try {
			await deleteContact(category, contact.id);
			goto("/kontakte");
		} catch (e: any) {
			error = e.message;
		}
	}
</script>

<div class="flex items-center gap-4 mb-6">
	<Button variant="outline" href="/kontakte">Zurück</Button>
	<div>
		<h2 class="text-3xl font-bold tracking-tight">{name || "Kontakt"}</h2>
		<p class="text-muted-foreground">Kontaktdetails bearbeiten</p>
	</div>
</div>

<div class="max-w-2xl mx-auto">
	{#if error}
		<div class="rounded-md bg-red-50 p-4 text-red-800 text-sm mb-4">
			{error}
		</div>
	{/if}
	{#if success}
		<div class="rounded-md bg-green-50 p-4 text-green-800 text-sm mb-4">
			{success}
		</div>
	{/if}

	{#if loading}
		<p class="text-muted-foreground">Laden...</p>
	{:else if contact}
		<div class="space-y-6">
			<!-- Contact Details Card -->
			<Card.Root>
				<Card.Header>
					<Card.Title>Kontaktdaten</Card.Title>
				</Card.Header>
				<Card.Content>
					<div class="grid gap-4">
						<div class="grid gap-2">
							<Label for="name">Name</Label>
							<Input id="name" bind:value={name} />
						</div>
						<div class="grid gap-2">
							<Label for="phone">Telefon</Label>
							<Input id="phone" bind:value={phone} />
						</div>
						<div class="grid gap-2">
							<Label for="address">Adresse</Label>
							<Input
								id="address"
								bind:value={address}
								placeholder="Strasse, PLZ Ort"
							/>
							<p class="text-xs text-muted-foreground">
								Bei Änderung wird die Kartenposition automatisch aktualisiert
							</p>
						</div>
						<div class="grid gap-2">
							<Label for="zipcode">PLZ</Label>
							<Input id="zipcode" bind:value={zipcode} />
						</div>
					</div>
				</Card.Content>
			</Card.Root>

			<!-- Fallback Numbers -->
			<FallbackList
				{fallbacks}
				onchange={(f) => {
					fallbacks = f;
				}}
			/>

			<!-- Actions -->
			<div class="flex gap-4">
				<Button onclick={handleSave} disabled={saving}>
					{saving ? "Speichern..." : "Speichern"}
				</Button>
				<Button
					variant="destructive"
					onclick={() => {
						deleteConfirmOpen = true;
					}}
				>
					Löschen
				</Button>
			</div>
		</div>
	{/if}
</div>

<!-- Delete Confirmation -->
<AlertDialog.Root bind:open={deleteConfirmOpen}>
	<AlertDialog.Content>
		<AlertDialog.Header>
			<AlertDialog.Title>Kontakt löschen</AlertDialog.Title>
			<AlertDialog.Description>
				Möchtest du <strong>{name}</strong> wirklich loeschen? Diese Aktion
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
