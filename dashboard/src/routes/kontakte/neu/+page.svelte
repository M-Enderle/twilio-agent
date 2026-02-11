<script lang="ts">
	import { goto } from "$app/navigation";
	import type { Category, FallbackContact } from "$lib/types";
	import { createContact, geocodeAddress } from "$lib/api";
	import * as Card from "$lib/components/ui/card/index.js";
	import { Button } from "$lib/components/ui/button/index.js";
	import { Input } from "$lib/components/ui/input/index.js";
	import { Label } from "$lib/components/ui/label/index.js";
	import FallbackList from "$lib/components/FallbackList.svelte";

	let name = $state("");
	let phone = $state("");
	let address = $state("");
	let zipcode = $state("");
	let category = $state<Category>("locksmith");
	let fallbacks = $state<FallbackContact[]>([]);
	let saving = $state(false);
	let error = $state("");

	async function handleCreate() {
		if (!name.trim() || !phone.trim()) {
			error = "Name und Telefon sind erforderlich";
			return;
		}

		saving = true;
		error = "";

		try {
			// Geocode the address
			let latitude: number | undefined;
			let longitude: number | undefined;

			const fullAddress = `${address}, ${zipcode}`.trim();
			if (fullAddress.length > 2) {
				try {
					const geo = await geocodeAddress(fullAddress);
					latitude = geo.latitude;
					longitude = geo.longitude;
				} catch {
					// Geocoding failed, continue without coords
				}
			}

			await createContact(category, {
				name,
				phone,
				address,
				zipcode,
				fallback: false,
				latitude,
				longitude,
				fallbacks_json: JSON.stringify(fallbacks),
			});

			goto(`/kontakte/${encodeURIComponent(name)}`);
		} catch (e: any) {
			error = e.message;
		} finally {
			saving = false;
		}
	}
</script>

<div class="max-w-2xl mx-auto">
	<div class="flex items-center gap-4 mb-6">
		<Button variant="outline" href="/kontakte">Zurück</Button>
		<div>
			<h2 class="text-3xl font-bold tracking-tight">Neuer Kontakt</h2>
			<p class="text-muted-foreground">Neuen Dienstleister anlegen</p>
		</div>
	</div>

	{#if error}
		<div class="rounded-md bg-red-50 p-4 text-red-800 text-sm mb-4">
			{error}
		</div>
	{/if}

	<div class="space-y-6">
		<Card.Root>
			<Card.Header>
				<Card.Title>Kontaktdaten</Card.Title>
			</Card.Header>
			<Card.Content>
				<div class="grid gap-4">
					<div class="grid gap-2">
						<Label for="category">Kategorie</Label>
						<select
							id="category"
							bind:value={category}
							class="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
						>
							<option value="locksmith">Schlüsseldienst</option>
							<option value="towing">Abschleppdienst</option>
						</select>
					</div>
					<div class="grid gap-2">
						<Label for="name">Name *</Label>
						<Input id="name" bind:value={name} required />
					</div>
					<div class="grid gap-2">
						<Label for="phone">Telefon *</Label>
						<Input id="phone" bind:value={phone} placeholder="+49..." required />
					</div>
					<div class="grid gap-2">
						<Label for="address">Adresse</Label>
						<Input
							id="address"
							bind:value={address}
							placeholder="Strasse, PLZ Ort"
						/>
						<p class="text-xs text-muted-foreground">
							Wird für die Kartenposition verwendet
						</p>
					</div>
					<div class="grid gap-2">
						<Label for="zipcode">PLZ</Label>
						<Input id="zipcode" bind:value={zipcode} />
					</div>
				</div>
			</Card.Content>
		</Card.Root>

		<FallbackList
			{fallbacks}
			onchange={(f) => {
				fallbacks = f;
			}}
		/>

		<Button onclick={handleCreate} disabled={saving}>
			{saving ? "Erstellen..." : "Erstellen"}
		</Button>
	</div>
</div>
