<script lang="ts">
	import "../app.css";
	import { page } from "$app/state";
	import * as Sidebar from "$lib/components/ui/sidebar/index.js";
	import SettingsIcon from "@lucide/svelte/icons/settings";
	import MapPinIcon from "@lucide/svelte/icons/map-pin";
	import PhoneIcon from "@lucide/svelte/icons/phone";
	import EuroIcon from "@lucide/svelte/icons/euro";
	import MessageSquareTextIcon from "@lucide/svelte/icons/message-square-text";
	import LogOutIcon from "@lucide/svelte/icons/log-out";
	import { setToken } from "$lib/api";
	import { browser } from "$app/environment";
	import { SERVICES, type ServiceId } from "$lib/types";
	import { getSelectedService, setSelectedService } from "$lib/service.svelte";

	let { children, data } = $props();

	// Set API URL and token synchronously so child components can use them
	// immediately (before onMount). This prevents a race where the first API
	// call falls back to hostname:8000 which isn't in the CSP.
	if (browser) {
		if (data.apiUrl) {
			window.__API_URL__ = data.apiUrl;
		}
		if (data.accessToken) {
			setToken(data.accessToken);
		}
	}

	const navItems = [
		{ href: "/standorte", label: "Standorte", icon: MapPinIcon },
		{ href: "/anrufe", label: "Anrufe", icon: PhoneIcon },
		{ href: "/preise", label: "Preise", icon: EuroIcon },
		{ href: "/ansagen", label: "Ansagen", icon: MessageSquareTextIcon },
		{ href: "/einstellungen", label: "Einstellungen", icon: SettingsIcon },
	];

	const isAuthPage = $derived(page.url.pathname.startsWith("/auth"));
	const selectedService = $derived(getSelectedService());
</script>

<svelte:head>
	<title>Notdienststation Dashboard</title>
</svelte:head>

{#if isAuthPage}
	{@render children()}
{:else}
	<Sidebar.Provider>
		<Sidebar.Root>
			<Sidebar.Header>
				<div class="flex justify-center py-6">
					<img src="https://notdienststation.de/static/logos/notdienst-800.png" alt="Notdienststation" class="h-16 object-contain" />
				</div>
			</Sidebar.Header>
			<Sidebar.Content>
				<Sidebar.Group>
					<Sidebar.GroupLabel>Dienst</Sidebar.GroupLabel>
					<Sidebar.GroupContent>
						<div class="px-2">
							<select
								aria-label="Dienst auswählen"
								class="flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
								value={selectedService}
								onchange={(e) => setSelectedService((e.target as HTMLSelectElement).value as ServiceId)}
							>
								{#each SERVICES as svc}
									<option value={svc.id}>{svc.shortLabel}</option>
								{/each}
							</select>
						</div>
					</Sidebar.GroupContent>
				</Sidebar.Group>
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
						<Sidebar.MenuButton>
							{#snippet child({ props })}
								<a href="/auth/logout" {...props}>
									<LogOutIcon />
									<span>Abmelden</span>
								</a>
							{/snippet}
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
{/if}
