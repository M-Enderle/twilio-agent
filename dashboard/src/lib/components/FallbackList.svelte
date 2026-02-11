<script lang="ts">
	import type { FallbackContact } from "$lib/types";
	import { Button } from "$lib/components/ui/button/index.js";
	import { Input } from "$lib/components/ui/input/index.js";
	import { Label } from "$lib/components/ui/label/index.js";
	import * as Card from "$lib/components/ui/card/index.js";
	import GripVerticalIcon from "@lucide/svelte/icons/grip-vertical";

	interface Props {
		fallbacks: FallbackContact[];
		onchange: (fallbacks: FallbackContact[]) => void;
	}

	let { fallbacks = [], onchange }: Props = $props();

	let newName = $state("");
	let newPhone = $state("");
	let draggedIndex = $state<number | null>(null);
	let dragOverIndex = $state<number | null>(null);

	function addFallback() {
		if (!newName.trim() || !newPhone.trim()) return;
		const updated = [
			...fallbacks,
			{
				id: crypto.randomUUID(),
				name: newName.trim(),
				phone: newPhone.trim(),
			},
		];
		onchange(updated);
		newName = "";
		newPhone = "";
	}

	function removeFallback(id: string) {
		onchange(fallbacks.filter((f) => f.id !== id));
	}

	function updateFallback(id: string, field: "name" | "phone", value: string) {
		onchange(
			fallbacks.map((f) => (f.id === id ? { ...f, [field]: value } : f))
		);
	}

	function handleDragStart(e: DragEvent, index: number) {
		draggedIndex = index;
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
		dragOverIndex = index;
	}

	function handleDragLeave() {
		dragOverIndex = null;
	}

	function handleDrop(e: DragEvent, targetIndex: number) {
		e.preventDefault();
		if (draggedIndex === null || draggedIndex === targetIndex) {
			draggedIndex = null;
			dragOverIndex = null;
			return;
		}

		const updated = [...fallbacks];
		const [removed] = updated.splice(draggedIndex, 1);
		updated.splice(targetIndex, 0, removed);
		onchange(updated);

		draggedIndex = null;
		dragOverIndex = null;
	}

	function handleDragEnd() {
		draggedIndex = null;
		dragOverIndex = null;
	}
</script>

<Card.Root>
	<Card.Header>
		<Card.Title>Fallback-Nummern</Card.Title>
		<Card.Description>
			Alternative Kontakte wenn Hauptkontakt nicht erreichbar
		</Card.Description>
	</Card.Header>
	<Card.Content>
		<div class="space-y-2">
			{#each fallbacks as fb, index (fb.id)}
				<div
					class="flex gap-2 items-end p-2 rounded-md border transition-colors {draggedIndex === index ? 'opacity-50 border-dashed' : ''} {dragOverIndex === index && draggedIndex !== index ? 'border-primary bg-primary/5' : 'border-transparent'}"
					draggable="true"
					ondragstart={(e) => handleDragStart(e, index)}
					ondragover={(e) => handleDragOver(e, index)}
					ondragleave={handleDragLeave}
					ondrop={(e) => handleDrop(e, index)}
					ondragend={handleDragEnd}
					role="listitem"
				>
					<div
						class="flex items-center cursor-grab active:cursor-grabbing text-muted-foreground hover:text-foreground"
					>
						<GripVerticalIcon class="h-5 w-5" />
					</div>
					<div class="flex-1 grid gap-2">
						<Label>Name</Label>
						<Input
							value={fb.name}
							oninput={(e) =>
								updateFallback(fb.id, "name", e.currentTarget.value)}
						/>
					</div>
					<div class="flex-1 grid gap-2">
						<Label>Telefon</Label>
						<Input
							value={fb.phone}
							oninput={(e) =>
								updateFallback(fb.id, "phone", e.currentTarget.value)}
						/>
					</div>
					<Button
						variant="destructive"
						size="sm"
						onclick={() => removeFallback(fb.id)}
					>
						X
					</Button>
				</div>
			{/each}

			{#if fallbacks.length === 0}
				<p class="text-sm text-muted-foreground">
					Keine Fallback-Nummern vorhanden
				</p>
			{/if}

			<!-- Add new fallback form -->
			<div class="grid grid-cols-[1fr_1fr_auto] gap-2 items-end border-t pt-4">
				<div class="grid gap-2">
					<Label>Neuer Name</Label>
					<Input bind:value={newName} placeholder="Name" />
				</div>
				<div class="grid gap-2">
					<Label>Telefon</Label>
					<Input bind:value={newPhone} placeholder="+49..." />
				</div>
				<Button onclick={addFallback}>Hinzufügen</Button>
			</div>
		</div>
	</Card.Content>
</Card.Root>
