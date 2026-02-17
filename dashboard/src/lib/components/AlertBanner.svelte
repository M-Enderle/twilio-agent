<script lang="ts">
	import CheckIcon from "@lucide/svelte/icons/check";
	import AlertCircleIcon from "@lucide/svelte/icons/alert-circle";

	interface Props {
		type: "error" | "success";
		message: string;
	}

	let { type, message }: Props = $props();
</script>

{#if message}
	{#if type === "error"}
		<div class="rounded-lg bg-red-50 border border-red-200 p-4 flex items-center gap-3" role="alert">
			<AlertCircleIcon class="h-5 w-5 text-red-600 shrink-0" />
			<span class="text-red-800 text-sm">{message}</span>
		</div>
	{:else}
		<div class="rounded-lg bg-green-50 border border-green-200 p-4 flex items-center gap-3" role="status">
			<CheckIcon class="h-5 w-5 text-green-600 shrink-0" />
			<span class="text-green-800 text-sm">{message}</span>
		</div>
	{/if}
{/if}
