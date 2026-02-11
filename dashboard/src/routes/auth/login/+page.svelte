<script lang="ts">
	import { dev } from "$app/environment";
</script>

<div class="flex min-h-screen items-center justify-center bg-white">
	<div class="flex flex-col items-center gap-8 p-12">
		<img
			src="https://notdienststation.de/static/logos/notdienst-800.png"
			alt="Notdienststation"
			class="h-24 object-contain"
		/>
		<h1 class="text-2xl font-semibold text-gray-800">Dashboard Login</h1>
		<a
			href="/auth/redirect"
			class="rounded-lg bg-blue-600 px-8 py-3 text-sm font-medium text-white transition-colors hover:bg-blue-700"
		>
			Mit PocketID anmelden
		</a>
		{#if dev}
			<a
				href="/auth/dev-skip"
				class="rounded-lg border border-gray-300 px-8 py-3 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-100"
			>
				Login überspringen (Dev)
			</a>
		{/if}
	</div>
</div>
