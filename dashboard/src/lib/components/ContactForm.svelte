<script lang="ts">
	import type { Contact, Category } from "$lib/types";
	import * as Dialog from "$lib/components/ui/dialog/index.js";
	import { Button } from "$lib/components/ui/button/index.js";
	import { Input } from "$lib/components/ui/input/index.js";
	import { Label } from "$lib/components/ui/label/index.js";

	interface Props {
		open: boolean;
		contact?: Contact | null;
		category: Category;
		onsave: (category: Category, data: Partial<Contact>) => void;
		onclose: () => void;
	}

	let { open = $bindable(false), contact = null, category = $bindable("locksmith"), onsave, onclose }: Props = $props();

	let name = $state("");
	let phone = $state("");
	let address = $state("");
	let zipcode = $state("");
	let fallback = $state(false);

	$effect(() => {
		if (open && contact) {
			name = contact.name;
			phone = contact.phone;
			address = contact.address || "";
			zipcode = String(contact.zipcode || "");
			fallback = contact.fallback;
		} else if (open) {
			name = "";
			phone = "";
			address = "";
			zipcode = "";
			fallback = false;
		}
	});

	function handleSave() {
		onsave(category, { name, phone, address, zipcode, fallback });
		open = false;
	}

	const isEdit = $derived(!!contact);
	const title = $derived(isEdit ? "Kontakt bearbeiten" : "Neuer Kontakt");
</script>

<Dialog.Root bind:open onOpenChange={(v) => { if (!v) onclose(); }}>
	<Dialog.Content>
		<Dialog.Header>
			<Dialog.Title>{title}</Dialog.Title>
			<Dialog.Description>
				{isEdit ? "Kontaktdaten bearbeiten" : "Neuen Dienstleister hinzufügen"}
			</Dialog.Description>
		</Dialog.Header>
		<div class="grid gap-4 py-4">
			{#if !isEdit}
				<div class="grid gap-2">
					<Label>Kategorie</Label>
					<select bind:value={category} class="border-input bg-background flex h-9 w-full rounded-md border px-3 py-1 text-sm shadow-xs">
						<option value="locksmith">Schlüsseldienst</option>
						<option value="towing">Abschleppdienst</option>
					</select>
				</div>
			{/if}
			<div class="grid gap-2">
				<Label for="name">Name</Label>
				<Input id="name" bind:value={name} placeholder="Name" />
			</div>
			<div class="grid gap-2">
				<Label for="phone">Telefon</Label>
				<Input id="phone" bind:value={phone} placeholder="+49..." />
			</div>
			<div class="grid gap-2">
				<Label for="address">Adresse</Label>
				<Input id="address" bind:value={address} placeholder="Straße, PLZ Ort" />
			</div>
			<div class="grid gap-2">
				<Label for="zipcode">PLZ</Label>
				<Input id="zipcode" bind:value={zipcode} placeholder="87509" />
			</div>
			<div class="flex items-center gap-2">
				<input type="checkbox" id="fallback" bind:checked={fallback} class="h-4 w-4 rounded border-input" />
				<Label for="fallback">Fallback-Kontakt</Label>
			</div>
		</div>
		<Dialog.Footer>
			<Button variant="outline" onclick={() => { open = false; onclose(); }}>Abbrechen</Button>
			<Button onclick={handleSave}>{isEdit ? "Speichern" : "Erstellen"}</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
