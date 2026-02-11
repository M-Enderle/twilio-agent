<script lang="ts">
	import type { FallbackContact } from "$lib/types";
	import { Button } from "$lib/components/ui/button/index.js";
	import { Input } from "$lib/components/ui/input/index.js";
	import { Label } from "$lib/components/ui/label/index.js";
	import * as Card from "$lib/components/ui/card/index.js";

	interface Props {
		fallbacks: FallbackContact[];
		onchange: (fallbacks: FallbackContact[]) => void;
	}

	let { fallbacks = [], onchange }: Props = $props();

	let newName = $state("");
	let newPhone = $state("");

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
</script>

<Card.Root>
	<Card.Header>
		<Card.Title>Fallback-Nummern</Card.Title>
		<Card.Description>
			Alternative Kontakte wenn Hauptkontakt nicht erreichbar
		</Card.Description>
	</Card.Header>
	<Card.Content>
		<div class="space-y-4">
			{#each fallbacks as fb (fb.id)}
				<div class="flex gap-2 items-end">
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
