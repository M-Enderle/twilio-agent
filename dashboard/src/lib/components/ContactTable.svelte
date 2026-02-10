<script lang="ts">
	import type { Contact, Category } from "$lib/types";
	import { reorderContacts } from "$lib/api";
	import { Badge } from "$lib/components/ui/badge/index.js";
	import { Button } from "$lib/components/ui/button/index.js";

	interface Props {
		contacts: Contact[];
		category: Category;
		onedit: (contact: Contact) => void;
		ondelete: (contact: Contact) => void;
		onreorder: () => void;
	}

	let { contacts, category, onedit, ondelete, onreorder }: Props = $props();

	let dragIndex = $state<number | null>(null);
	let overIndex = $state<number | null>(null);

	function handleDragStart(e: DragEvent, index: number) {
		dragIndex = index;
		if (e.dataTransfer) {
			e.dataTransfer.effectAllowed = "move";
			e.dataTransfer.setData("text/plain", String(index));
		}
	}

	function handleDragOver(e: DragEvent, index: number) {
		e.preventDefault();
		if (e.dataTransfer) {
			e.dataTransfer.dropEffect = "move";
		}
		overIndex = index;
	}

	function handleDragLeave() {
		overIndex = null;
	}

	async function handleDrop(e: DragEvent, targetIndex: number) {
		e.preventDefault();
		overIndex = null;
		if (dragIndex === null || dragIndex === targetIndex) {
			dragIndex = null;
			return;
		}

		const reordered = [...contacts];
		const [moved] = reordered.splice(dragIndex, 1);
		reordered.splice(targetIndex, 0, moved);

		try {
			await reorderContacts(category, reordered.map((c) => c.id));
			onreorder();
		} catch (err) {
			console.error("Reorder failed:", err);
		}
		dragIndex = null;
	}

	function handleDragEnd() {
		dragIndex = null;
		overIndex = null;
	}
</script>

<div class="rounded-md border">
	<table class="w-full text-sm">
		<thead>
			<tr class="border-b bg-muted/50 text-left">
				<th class="w-10 px-3 py-3"></th>
				<th class="px-3 py-3 font-medium">Name</th>
				<th class="px-3 py-3 font-medium">Telefon</th>
				<th class="px-3 py-3 font-medium hidden md:table-cell">Adresse</th>
				<th class="px-3 py-3 font-medium hidden sm:table-cell">PLZ</th>
				<th class="px-3 py-3 font-medium">Status</th>
				<th class="px-3 py-3 font-medium text-right">Aktionen</th>
			</tr>
		</thead>
		<tbody>
			{#each contacts as contact, i (contact.id)}
				<tr
					class="border-b transition-colors hover:bg-muted/50 {dragIndex === i ? 'opacity-50' : ''} {overIndex === i ? 'bg-muted' : ''}"
					draggable="true"
					ondragstart={(e) => handleDragStart(e, i)}
					ondragover={(e) => handleDragOver(e, i)}
					ondragleave={handleDragLeave}
					ondrop={(e) => handleDrop(e, i)}
					ondragend={handleDragEnd}
				>
					<td class="px-3 py-3 cursor-grab text-muted-foreground select-none">⠿</td>
					<td class="px-3 py-3 font-medium">{contact.name}</td>
					<td class="px-3 py-3 text-muted-foreground">{contact.phone}</td>
					<td class="px-3 py-3 text-muted-foreground hidden md:table-cell">{contact.address || "–"}</td>
					<td class="px-3 py-3 text-muted-foreground hidden sm:table-cell">{contact.zipcode || "–"}</td>
					<td class="px-3 py-3">
						{#if contact.fallback}
							<Badge variant="secondary">Fallback</Badge>
						{/if}
					</td>
					<td class="px-3 py-3 text-right">
						<div class="flex gap-1 justify-end">
							<Button variant="outline" size="sm" onclick={() => onedit(contact)}>Bearbeiten</Button>
							<Button variant="destructive" size="sm" onclick={() => ondelete(contact)}>Löschen</Button>
						</div>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
</div>
