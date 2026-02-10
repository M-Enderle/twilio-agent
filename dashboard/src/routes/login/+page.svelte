<script lang="ts">
	import { signIn } from "@auth/sveltekit/client";
</script>

<div class="flex min-h-screen items-center justify-center bg-gray-50">
	<div class="flex flex-col items-center gap-8 rounded-xl bg-white p-12 shadow-lg">
		<img
			src="https://notdienststation.de/static/logos/notdienst-800.png"
			alt="Notdienststation"
			class="h-20 object-contain"
		/>
		<h1 class="text-xl font-semibold text-gray-800">Dashboard Login</h1>
		<button
			onclick={() => signIn("pocketid")}
			class="rounded-lg bg-blue-600 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-blue-700"
		>
			Mit PocketID anmelden
		</button>
	</div>
</div>
