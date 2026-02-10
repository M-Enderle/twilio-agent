<script lang="ts">
	import "../app.css";
	import { page } from "$app/state";
	import * as Sidebar from "$lib/components/ui/sidebar/index.js";
	import SettingsIcon from "@lucide/svelte/icons/settings";
	import UsersIcon from "@lucide/svelte/icons/users";
	import LogOutIcon from "@lucide/svelte/icons/log-out";
	import { signOut } from "@auth/sveltekit/client";
	import { setToken } from "$lib/api";
	import { onMount } from "svelte";

	let { children, data } = $props();

	const navItems = [
		{ href: "/kontakte", label: "Kontakte", icon: UsersIcon },
		{ href: "/einstellungen", label: "Einstellungen", icon: SettingsIcon },
	];

	onMount(() => {
		if (data.session?.accessToken) {
			setToken(data.session.accessToken);
		}
	});
</script>

<svelte:head>
	<title>Notdienststation Dashboard</title>
</svelte:head>

<Sidebar.Provider>
	<Sidebar.Root>
		<Sidebar.Header>
			<div class="flex justify-center py-6">
				<img src="https://notdienststation.de/static/logos/notdienst-800.png" alt="Notdienststation" class="h-16 object-contain" />
			</div>
		</Sidebar.Header>
		<Sidebar.Content>
			<Sidebar.Group>
				<Sidebar.GroupLabel>Navigation</Sidebar.GroupLabel>
				<Sidebar.GroupContent>
					<Sidebar.Menu>
						{#each navItems as item}
							<Sidebar.MenuItem>
								<Sidebar.MenuButton isActive={page.url.pathname.startsWith(item.href)}>
									{#snippet child({ props })}
										<a href={item.href} {...props}>
											<item.icon />
											<span>{item.label}</span>
										</a>
									{/snippet}
								</Sidebar.MenuButton>
							</Sidebar.MenuItem>
						{/each}
					</Sidebar.Menu>
				</Sidebar.GroupContent>
			</Sidebar.Group>
		</Sidebar.Content>
		<Sidebar.Footer>
			<Sidebar.Menu>
				<Sidebar.MenuItem>
					<Sidebar.MenuButton onclick={() => signOut()}>
						<LogOutIcon />
						<span>Abmelden</span>
					</Sidebar.MenuButton>
				</Sidebar.MenuItem>
			</Sidebar.Menu>
		</Sidebar.Footer>
	</Sidebar.Root>

	<main class="flex-1 p-8">
		<Sidebar.Trigger class="mb-4 md:hidden" />
		{@render children()}
	</main>
</Sidebar.Provider>
