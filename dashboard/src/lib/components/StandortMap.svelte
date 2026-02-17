<script lang="ts">
	import { onMount, onDestroy } from "svelte";
	import type { Standort, CallSummary } from "$lib/types";
	import type L from "leaflet";
	import { getTerritories } from "$lib/api";
	import type { ServiceId } from "$lib/types";

	interface Props {
		standorte: Standort[];
		calls: CallSummary[];
		serviceId: ServiceId;
		onstandortclick?: (id: string) => void;
	}

	let { standorte, calls, serviceId, onstandortclick }: Props = $props();
	let mapContainer: HTMLDivElement;
	let map: L.Map | null = null;
	let markers: L.Marker[] = [];
	let callMarkers: L.Marker[] = [];
	let territoryRects: L.Rectangle[] = [];
	let borderLines: L.Polyline[] = [];
	let leaflet: typeof L | null = null;

	// Loading state for territory display
	let loadingTerritories = $state(false);

	// Expose refresh function (now only refreshes display, doesn't recalculate)
	export function refresh() {
		if (map && leaflet) {
			// Clear and reload from cache
			territoryGrid = [];
			territoryBounds = null;
			territoryRects.forEach((r) => r.remove());
			territoryRects = [];
			borderLines.forEach((l) => l.remove());
			borderLines = [];
			updateMarkers();
			loadCachedTerritories();
		}
	}

	// Grid configuration (matched with backend)
	const GRID_SIZE = 32;

	// Color palette for territory regions
	const regionColors = [
		"rgba(59, 130, 246, 0.4)",   // blue
		"rgba(16, 185, 129, 0.4)",   // green
		"rgba(249, 115, 22, 0.4)",   // orange
		"rgba(139, 92, 246, 0.4)",   // purple
		"rgba(236, 72, 153, 0.4)",   // pink
		"rgba(245, 158, 11, 0.4)",   // amber
		"rgba(6, 182, 212, 0.4)",    // cyan
		"rgba(239, 68, 68, 0.4)",    // red
		"rgba(34, 197, 94, 0.4)",    // emerald
		"rgba(168, 85, 247, 0.4)",   // violet
	];

	// Territory grid data
	let territoryGrid: { lat: number; lng: number; contactIndex: number }[] = [];
	// Stored bounds from when the grid was computed (ensures render uses matching bounds)
	let territoryBounds: { minLat: number; maxLat: number; minLng: number; maxLng: number } | null = null;
	// Guard against concurrent fetches
	let fetchInProgress = false;

	const mappableStandorte = $derived(
		standorte
			.filter((s) => s.latitude && s.longitude)
	);

	// Filter calls from past 30 days with location data
	const recentCalls = $derived.by(() => {
		const thirtyDaysAgo = new Date();
		thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

		return calls.filter((call) => {
			if (!call.latitude || !call.longitude) return false;

			// Parse timestamp from call (format: YYYYMMDD_HHMMSS)
			const timestamp = call.timestamp;
			const dateStr = timestamp.split('_')[0]; // Get YYYYMMDD part
			const year = parseInt(dateStr.substring(0, 4));
			const month = parseInt(dateStr.substring(4, 6)) - 1;
			const day = parseInt(dateStr.substring(6, 8));
			const callDate = new Date(year, month, day);

			return callDate >= thirtyDaysAgo;
		});
	});

	onMount(async () => {
		leaflet = (await import("leaflet")).default;
		await import("leaflet/dist/leaflet.css");

		// Fix Leaflet marker icons issue with bundlers
		delete (leaflet.Icon.Default.prototype as any)._getIconUrl;
		leaflet.Icon.Default.mergeOptions({
			iconRetinaUrl: "/leaflet/marker-icon-2x.png",
			iconUrl: "/leaflet/marker-icon.png",
			shadowUrl: "/leaflet/marker-shadow.png",
		});

		// Center on Bavaria/Southern Germany
		map = leaflet.map(mapContainer).setView([48.6, 11.5], 8);

		leaflet
			.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
				attribution: "&copy; OpenStreetMap contributors",
			})
			.addTo(map);

		updateMarkers();
		loadCachedTerritories();
	});

	async function loadCachedTerritories() {
		if (!map || !leaflet || mappableStandorte.length < 2) return;
		if (fetchInProgress) return;
		fetchInProgress = true;

		loadingTerritories = true;

		try {
			// Load from backend cache (calculated daily at 4:00 AM by backend scheduler)
			const cached = await getTerritories(serviceId);
			if (cached.grid && cached.grid.length > 0 && cached.computed_at && !cached.is_partial) {
				// Complete cache - use it with its stored bounds
				console.log("Using cached territory data from", cached.computed_at);
				territoryGrid = cached.grid;
				territoryBounds = cached.bounds || null;
				renderTerritoryGrid();
			} else {
				console.log("No cached territories available yet. Territories are calculated daily at 4:00 AM.");
			}
		} catch (e) {
			console.log("No cached territories available yet:", e);
		} finally {
			loadingTerritories = false;
			fetchInProgress = false;
		}
	}

	function renderTerritoryGrid() {
		if (!map || !leaflet || territoryGrid.length === 0 || !territoryBounds) return;

		// Clear existing rectangles
		territoryRects.forEach((r) => r.remove());
		territoryRects = [];

		// Use stored bounds from cache
		const bounds = territoryBounds;
		const latStep = (bounds.maxLat - bounds.minLat) / (GRID_SIZE - 1);
		const lngStep = (bounds.maxLng - bounds.minLng) / (GRID_SIZE - 1);

		territoryGrid.forEach((cell) => {
			if (!map || !leaflet) return;

			const color = regionColors[cell.contactIndex % regionColors.length];
			const rect = leaflet.rectangle(
				[
					[cell.lat - latStep / 2, cell.lng - lngStep / 2],
					[cell.lat + latStep / 2, cell.lng + lngStep / 2],
				],
				{
					color: "transparent",
					weight: 0,
					fillColor: color,
					fillOpacity: 0.4,
				}
			).addTo(map);

			const standort = mappableStandorte[cell.contactIndex];
			if (standort) {
				rect.bindPopup(`<b>${standort.name}</b><br>${standort.address || "Keine Adresse"}`);
				rect.on("click", () => {
					onstandortclick?.(standort.id);
				});
			}

			territoryRects.push(rect);
		});

		// Render borders after rectangles
		renderTerritoryBorders();
	}

	function renderTerritoryBorders() {
		if (!map || !leaflet || territoryGrid.length === 0 || !territoryBounds) return;

		// Clear existing borders
		borderLines.forEach((l) => l.remove());
		borderLines = [];

		// Use stored bounds from cache
		const bounds = territoryBounds;
		const latStep = (bounds.maxLat - bounds.minLat) / (GRID_SIZE - 1);
		const lngStep = (bounds.maxLng - bounds.minLng) / (GRID_SIZE - 1);

		// Create lookup map: "lat,lng" -> contactIndex
		const cellMap = new Map<string, number>();
		territoryGrid.forEach((cell) => {
			const key = `${cell.lat.toFixed(4)},${cell.lng.toFixed(4)}`;
			cellMap.set(key, cell.contactIndex);
		});

		// Collect border segments to avoid duplicates
		const borderSegments: { from: [number, number]; to: [number, number] }[] = [];

		territoryGrid.forEach((cell) => {
			const myIndex = cell.contactIndex;

			// Check right neighbor
			const rightLng = cell.lng + lngStep;
			const rightKey = `${cell.lat.toFixed(4)},${rightLng.toFixed(4)}`;
			const rightIndex = cellMap.get(rightKey);
			if (rightIndex !== undefined && rightIndex !== myIndex) {
				borderSegments.push({
					from: [cell.lat - latStep / 2, cell.lng + lngStep / 2],
					to: [cell.lat + latStep / 2, cell.lng + lngStep / 2],
				});
			}

			// Check top neighbor
			const topLat = cell.lat + latStep;
			const topKey = `${topLat.toFixed(4)},${cell.lng.toFixed(4)}`;
			const topIndex = cellMap.get(topKey);
			if (topIndex !== undefined && topIndex !== myIndex) {
				borderSegments.push({
					from: [cell.lat + latStep / 2, cell.lng - lngStep / 2],
					to: [cell.lat + latStep / 2, cell.lng + lngStep / 2],
				});
			}
		});

		// Draw all border segments as thick dark lines
		borderSegments.forEach((seg) => {
			if (!map || !leaflet) return;
			const line = leaflet.polyline([seg.from, seg.to], {
				color: "#ef4444",
				weight: 3,
				opacity: 0.4,
			}).addTo(map);
			borderLines.push(line);
		});
	}

	function calculateCallOpacity(timestamp: string): number {
		// Parse timestamp (format: YYYYMMDD_HHMMSS)
		const dateStr = timestamp.split('_')[0];
		const year = parseInt(dateStr.substring(0, 4));
		const month = parseInt(dateStr.substring(4, 6)) - 1;
		const day = parseInt(dateStr.substring(6, 8));
		const callDate = new Date(year, month, day);

		const now = new Date();
		const thirtyDaysAgo = new Date();
		thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

		const totalRange = now.getTime() - thirtyDaysAgo.getTime();
		const callAge = now.getTime() - callDate.getTime();

		// Opacity from 0.2 (30 days ago) to 0.8 (today)
		const normalizedAge = callAge / totalRange;
		return 0.8 - (normalizedAge * 0.6);
	}

	function updateCallMarkers() {
		if (!map || !leaflet) return;

		// Clear existing call markers
		callMarkers.forEach((m) => m.remove());
		callMarkers = [];

		// Add pulsating red markers for recent calls
		recentCalls.forEach((call) => {
			if (!map || !leaflet || !call.latitude || !call.longitude) return;

			const opacity = calculateCallOpacity(call.timestamp);

			// Create a custom div icon for pulsating effect
			const icon = leaflet.divIcon({
				className: 'call-marker-container',
				html: `<div class="pulsating-call-marker" style="opacity: ${opacity};"></div>`,
				iconSize: [20, 20],
				iconAnchor: [10, 10]
			});

			const marker = leaflet.marker(
				[call.latitude, call.longitude],
				{ icon }
			).addTo(map);

			// Format location for popup
			let locationStr = "Unbekannter Standort";
			if (typeof call.location === 'object' && call.location.formatted_address) {
				locationStr = String(call.location.formatted_address);
			} else if (typeof call.location === 'string' && call.location.trim()) {
				locationStr = call.location;
			}

			// Format date for popup
			const dateStr = call.timestamp.split('_')[0];
			const year = dateStr.substring(0, 4);
			const month = dateStr.substring(4, 6);
			const day = dateStr.substring(6, 8);
			const formattedDate = `${day}.${month}.${year}`;

			marker.bindPopup(
				`<div style="min-width: 200px;">
					<b style="color: #ef4444;">📞 Anruf</b><br>
					<b>Datum:</b> ${formattedDate}<br>
					<b>Standort:</b> ${locationStr}<br>
					${call.intent ? `<b>Anliegen:</b> ${call.intent}<br>` : ''}
				</div>`
			);

			callMarkers.push(marker);
		});
	}

	function updateMarkers() {
		if (!map || !leaflet) return;

		// Clear existing markers
		markers.forEach((m) => m.remove());
		markers = [];

		// Add markers for each standort
		mappableStandorte.forEach((standort) => {
			if (!map || !leaflet || !standort.latitude || !standort.longitude) return;

			const marker = leaflet
				.marker([standort.latitude, standort.longitude])
				.addTo(map)
				.bindPopup(
					`<b>${standort.name}</b><br>${standort.address || "Keine Adresse"}`
				);

			marker.on("click", () => {
				onstandortclick?.(standort.id);
			});

			markers.push(marker);
		});

		// Add call markers
		updateCallMarkers();

		// Fit bounds to include both standorte and call markers
		if ((markers.length > 0 || callMarkers.length > 0) && map && leaflet) {
			const allMarkers = [...markers, ...callMarkers];
			const group = leaflet.featureGroup(allMarkers);
			map.fitBounds(group.getBounds().pad(0.1));
		}
	}

	$effect(() => {
		// Re-render markers and territories when standorte, calls, or serviceId change
		mappableStandorte;
		recentCalls;
		serviceId;
		if (map && leaflet) {
			// Clear existing territories
			territoryRects.forEach((r) => r.remove());
			territoryRects = [];
			borderLines.forEach((l) => l.remove());
			borderLines = [];
			territoryGrid = [];
			territoryBounds = null;

			updateMarkers();
			loadCachedTerritories();
		}
	});

	onDestroy(() => {
		territoryRects.forEach((r) => r.remove());
		borderLines.forEach((l) => l.remove());
		markers.forEach((m) => m.remove());
		callMarkers.forEach((m) => m.remove());
		map?.remove();
	});
</script>

<div class="relative z-0 w-full h-full min-h-[500px]">
	<div bind:this={mapContainer} class="w-full h-full"></div>

	{#if loadingTerritories}
		<div class="absolute top-3 left-3 bg-white/95 px-4 py-2 rounded-lg shadow-lg z-[1000] flex items-center gap-3">
			<div class="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
			<span class="text-sm font-medium text-gray-700">
				Lade Gebiete...
			</span>
		</div>
	{/if}
</div>

<style>
	:global(.call-marker-container) {
		background: transparent !important;
		border: none !important;
	}

	:global(.pulsating-call-marker) {
		width: 16px;
		height: 16px;
		background-color: #ef4444;
		border: 2px solid #dc2626;
		border-radius: 50%;
		position: absolute;
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
		animation: pulse-call 2s ease-in-out infinite;
	}

	@keyframes pulse-call {
		0%, 100% {
			box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7);
		}
		50% {
			box-shadow: 0 0 0 8px rgba(239, 68, 68, 0);
		}
	}
</style>
