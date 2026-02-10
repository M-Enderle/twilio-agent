<script lang="ts">
	import { onMount } from "svelte";
	import type { Contact, Category } from "$lib/types";
	import { getContacts, createContact, updateContact, deleteContact } from "$lib/api";
	import ContactTable from "$lib/components/ContactTable.svelte";
	import ContactForm from "$lib/components/ContactForm.svelte";
	import { Button } from "$lib/components/ui/button/index.js";
	import { Separator } from "$lib/components/ui/separator/index.js";
	import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";

	let contacts = $state<Record<Category, Contact[]>>({ locksmith: [], towing: [] });
	let loading = $state(true);
	let error = $state("");

	// Contact form state
	let formOpen = $state(false);
	let editingContact = $state<Contact | null>(null);
	let formCategory = $state<Category>("locksmith");

	// Delete confirm state
	let deleteConfirmOpen = $state(false);
	let deleteTarget = $state<{ category: Category; contact: Contact } | null>(null);

	async function loadContacts() {
		try {
			contacts = await getContacts() as Record<Category, Contact[]>;
			error = "";
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	onMount(loadContacts);

	function openNewContact() {
		editingContact = null;
		formCategory = "locksmith";
		formOpen = true;
	}

	function openEditContact(category: Category, contact: Contact) {
		editingContact = contact;
		formCategory = category;
		formOpen = true;
	}

	async function handleSaveContact(category: Category, data: Partial<Contact>) {
		try {
			if (editingContact) {
				await updateContact(category, editingContact.id, data);
			} else {
				await createContact(category, data as any);
			}
			await loadContacts();
		} catch (e: any) {
			error = e.message;
		}
	}

	function confirmDelete(category: Category, contact: Contact) {
		deleteTarget = { category, contact };
		deleteConfirmOpen = true;
	}

	async function handleDelete() {
		if (!deleteTarget) return;
		try {
			await deleteContact(deleteTarget.category, deleteTarget.contact.id);
			deleteConfirmOpen = false;
			deleteTarget = null;
			await loadContacts();
		} catch (e: any) {
			error = e.message;
		}
	}

	const sections: { key: Category; label: string }[] = [
		{ key: "locksmith", label: "Schlüsseldienst" },
		{ key: "towing", label: "Abschleppdienst" },
	];
</script>

<div class="space-y-8">
	<div class="flex items-center justify-between">
		<div>
			<h2 class="text-3xl font-bold tracking-tight">Kontakte</h2>
			<p class="text-muted-foreground">Verwalte die Dienstleister-Kontakte</p>
		</div>
		<Button onclick={openNewContact}>+ Kontakt</Button>
	</div>

	{#if error}
		<div class="rounded-md bg-red-50 p-4 text-red-800 text-sm">{error}</div>
	{/if}

	{#if loading}
		<p class="text-muted-foreground">Laden...</p>
	{:else}
		{#each sections as section}
			<div>
				<h3 class="text-xl font-semibold mb-4">{section.label}</h3>
				{#if contacts[section.key]?.length}
					<ContactTable
						contacts={contacts[section.key]}
						category={section.key}
						onedit={(contact) => openEditContact(section.key, contact)}
						ondelete={(contact) => confirmDelete(section.key, contact)}
						onreorder={loadContacts}
					/>
				{:else}
					<p class="text-sm text-muted-foreground">Keine Kontakte vorhanden</p>
				{/if}
			</div>
			{#if section.key !== "towing"}
				<Separator />
			{/if}
		{/each}
	{/if}
</div>

<!-- Contact Form Dialog -->
<ContactForm
	bind:open={formOpen}
	contact={editingContact}
	bind:category={formCategory}
	onsave={handleSaveContact}
	onclose={() => { formOpen = false; }}
/>

<!-- Delete Confirmation -->
<AlertDialog.Root bind:open={deleteConfirmOpen}>
	<AlertDialog.Content>
		<AlertDialog.Header>
			<AlertDialog.Title>Kontakt löschen</AlertDialog.Title>
			<AlertDialog.Description>
				Möchtest du <strong>{deleteTarget?.contact.name}</strong> wirklich löschen? Diese Aktion kann nicht rückgängig gemacht werden.
			</AlertDialog.Description>
		</AlertDialog.Header>
		<AlertDialog.Footer>
			<AlertDialog.Cancel>Abbrechen</AlertDialog.Cancel>
			<AlertDialog.Action onclick={handleDelete} class="bg-destructive text-white hover:bg-destructive/90">Löschen</AlertDialog.Action>
		</AlertDialog.Footer>
	</AlertDialog.Content>
</AlertDialog.Root>
