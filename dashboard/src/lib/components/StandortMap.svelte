<script lang="ts">
	import { onMount, onDestroy } from "svelte";
	import type { Standort } from "$lib/types";
	import type L from "leaflet";
	import { getTerritories, saveTerritories } from "$lib/api";
	import type { ServiceId } from "$lib/types";

	interface Props {
		standorte: Standort[];
		serviceId: ServiceId;
		onstandortclick?: (id: string) => void;
	}

	let { standorte, serviceId, onstandortclick }: Props = $props();
	let mapContainer: HTMLDivElement;
	let map: L.Map | null = null;
	let markers: L.Marker[] = [];
	let territoryRects: L.Rectangle[] = [];
	let borderLines: L.Polyline[] = [];
	let leaflet: typeof L | null = null;

	// Loading state for OSRM requests
	let loadingTerritories = $state(false);
	let loadingProgress = $state(0);

	// Expose refresh function
	export function refresh() {
		if (map && leaflet) {
			// Clear cache and recompute
			territoryGrid = [];
			territoryBounds = null;
			fetchInProgress = false;
			territoryRects.forEach((r) => r.remove());
			territoryRects = [];
			borderLines.forEach((l) => l.remove());
			borderLines = [];
			updateMarkers();
			fetchDrivingTimeTerritories(true);
		}
	}

	// Grid configuration
	const GRID_SIZE = 32; // 32x32 = 1024 points
	const BATCH_SIZE = 20;
	const MAX_DISTANCE_KM = 50; // Only include grid points within this distance of any contact

	// Haversine distance in km
	function haversineKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
		const R = 6371;
		const dLat = ((lat2 - lat1) * Math.PI) / 180;
		const dLng = ((lng2 - lng1) * Math.PI) / 180;
		const a =
			Math.sin(dLat / 2) ** 2 +
			Math.cos((lat1 * Math.PI) / 180) *
				Math.cos((lat2 * Math.PI) / 180) *
				Math.sin(dLng / 2) ** 2;
		return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
	}

	// Compute dynamic bounds from standorte + 50km padding
	function computeBounds(items: typeof mappableStandorte): { minLat: number; maxLat: number; minLng: number; maxLng: number } {
		const lats = items.filter(c => c.latitude).map(c => c.latitude!);
		const lngs = items.filter(c => c.longitude).map(c => c.longitude!);

		if (lats.length === 0 || lngs.length === 0) {
			// Fallback to Germany if no standorte
			return { minLat: 47.2, maxLat: 55.0, minLng: 5.8, maxLng: 15.0 };
		}

		// ~50km in degrees (rough approximation)
		const latPadding = MAX_DISTANCE_KM / 111; // 1 degree lat ≈ 111km
		const avgLat = (Math.min(...lats) + Math.max(...lats)) / 2;
		const lngPadding = MAX_DISTANCE_KM / (111 * Math.cos(avgLat * Math.PI / 180));

		return {
			minLat: Math.min(...lats) - latPadding,
			maxLat: Math.max(...lats) + latPadding,
			minLng: Math.min(...lngs) - lngPadding,
			maxLng: Math.max(...lngs) + lngPadding,
		};
	}

	function isPointRelevant(lat: number, lng: number, items: typeof mappableStandorte): boolean {
		for (const c of items) {
			if (c.latitude && c.longitude) {
				const dist = haversineKm(lat, lng, c.latitude, c.longitude);
				if (dist <= MAX_DISTANCE_KM) return true;
			}
		}
		return false;
	}

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
		fetchDrivingTimeTerritories();
	});

	function computeLocationsHash(): string {
		return mappableStandorte
			.map((c) => `${c.latitude?.toFixed(6)},${c.longitude?.toFixed(6)}`)
			.sort()
			.join("|")
			.slice(0, 12);
	}

	async function fetchDrivingTimeTerritories(forceRefresh = false) {
		if (!map || !leaflet || mappableStandorte.length < 2) return;
		if (fetchInProgress) return;
		fetchInProgress = true;

		loadingTerritories = true;
		loadingProgress = 0;

		const locationsHash = computeLocationsHash();

		try {
			// Try to load from backend cache first (unless force refresh)
			let cachedResults: { lat: number; lng: number; contactIndex: number }[] = [];
			let resumeFromPartial = false;

			if (!forceRefresh) {
				try {
					const cached = await getTerritories(serviceId);
					if (cached.grid && cached.grid.length > 0) {
						if (cached.computed_at && !cached.is_partial) {
							// Complete cache - use it with its stored bounds
							console.log("Using cached territory data from", cached.computed_at);
							territoryGrid = cached.grid;
							territoryBounds = cached.bounds || null;
							loadingTerritories = false;
							renderTerritoryGrid();
							return;
						} else if (cached.is_partial) {
							// Partial cache - resume from it
							console.log(`Resuming from partial cache (${cached.grid.length} points)`);
							cachedResults = cached.grid;
							resumeFromPartial = true;
						}
					}
				} catch (e) {
					console.log("No cached territories, computing from scratch...");
				}
			} else {
				console.log("Force refresh - computing territories from scratch...");
			}

			// Compute dynamic bounds from contact locations + 50km padding
			const bounds = computeBounds(mappableStandorte);
			territoryBounds = bounds;
			console.log(`Dynamic bounds: lat ${bounds.minLat.toFixed(2)}-${bounds.maxLat.toFixed(2)}, lng ${bounds.minLng.toFixed(2)}-${bounds.maxLng.toFixed(2)}`);

			// Generate grid points within bounds
			const allGridPoints: { lat: number; lng: number }[] = [];
			for (let i = 0; i < GRID_SIZE; i++) {
				for (let j = 0; j < GRID_SIZE; j++) {
					allGridPoints.push({
						lat: bounds.minLat + (i / (GRID_SIZE - 1)) * (bounds.maxLat - bounds.minLat),
						lng: bounds.minLng + (j / (GRID_SIZE - 1)) * (bounds.maxLng - bounds.minLng),
					});
				}
			}
			// Filter to only points within 50km of any standort
			const gridPoints = allGridPoints.filter((p) => isPointRelevant(p.lat, p.lng, mappableStandorte));
			console.log(`Using ${gridPoints.length} grid points (filtered from ${allGridPoints.length})`);

			// If resuming, filter out already computed points
			let pointsToCompute = gridPoints;
			if (resumeFromPartial && cachedResults.length > 0) {
				const computedSet = new Set(cachedResults.map((p) => `${p.lat.toFixed(4)},${p.lng.toFixed(4)}`));
				pointsToCompute = gridPoints.filter((p) => !computedSet.has(`${p.lat.toFixed(4)},${p.lng.toFixed(4)}`));
				console.log(`${pointsToCompute.length} points remaining to compute`);
			}

			// Kontakt coordinates (reused in each batch)
			const standortCoords = mappableStandorte.map((c) => `${c.longitude},${c.latitude}`);
			const results: { lat: number; lng: number; contactIndex: number }[] = [...cachedResults];

			// Process in batches
			let batchCount = 0;
			for (let batchStart = 0; batchStart < pointsToCompute.length; batchStart += BATCH_SIZE) {
				const batchPoints = pointsToCompute.slice(batchStart, batchStart + BATCH_SIZE);

				// Build OSRM request: batch grid points as sources, standorte as destinations
				const batchCoords = [
					...batchPoints.map((p) => `${p.lng},${p.lat}`),
					...standortCoords,
				].join(";");

				const sources = batchPoints.map((_, i) => i).join(";");
				const destinations = standortCoords.map((_, i) => batchPoints.length + i).join(";");

				try {
					const response = await fetch(
						`https://router.project-osrm.org/table/v1/driving/${batchCoords}?sources=${sources}&destinations=${destinations}`
					);
					const data = await response.json();

					if (data.code === "Ok") {
						batchPoints.forEach((point, i) => {
							const durations = data.durations[i];
							let minIndex = 0;
							let minTime = durations[0] ?? Infinity;

							durations.forEach((time: number | null, j: number) => {
								if (time !== null && time < minTime) {
									minTime = time;
									minIndex = j;
								}
							});

							results.push({ ...point, contactIndex: minIndex });
						});
					}
				} catch (e) {
					console.error("OSRM batch failed:", e);
				}

				batchCount++;
				loadingProgress = Math.round((results.length / gridPoints.length) * 100);

				// Save intermediate results every 5 batches
				if (batchCount % 5 === 0) {
					try {
						await saveTerritories(serviceId, {
							grid: results,
							locations_hash: locationsHash,
							computed_at: null,
							is_partial: true,
							total_points: gridPoints.length,
							bounds,
						});
						console.log(`Saved intermediate progress: ${results.length}/${gridPoints.length} points`);
					} catch (e) {
						// Ignore intermediate save errors
					}
				}

				// Update display with partial results
				territoryGrid = results;
				renderTerritoryGrid();

				// Small delay between batches
				await new Promise((r) => setTimeout(r, 100));
			}

			territoryGrid = results;

			// Save final results to backend cache
			try {
				await saveTerritories(serviceId, {
					grid: results,
					locations_hash: locationsHash,
					computed_at: new Date().toISOString(),
					is_partial: false,
					total_points: gridPoints.length,
					bounds,
				});
				console.log("Saved complete territory data to cache");
			} catch (e) {
				console.error("Failed to save territories to cache:", e);
			}

			renderTerritoryGrid();
		} finally {
			loadingTerritories = false;
			fetchInProgress = false;
		}
	}

	function renderTerritoryGrid() {
		if (!map || !leaflet || territoryGrid.length === 0) return;

		// Clear existing rectangles
		territoryRects.forEach((r) => r.remove());
		territoryRects = [];

		// Use stored bounds (from computation or cache) to ensure cell sizing matches grid positions
		const bounds = territoryBounds || computeBounds(mappableStandorte);
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
		if (!map || !leaflet || territoryGrid.length === 0) return;

		// Clear existing borders
		borderLines.forEach((l) => l.remove());
		borderLines = [];

		// Use stored bounds to match grid cell positions
		const bounds = territoryBounds || computeBounds(mappableStandorte);
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

		// Fit bounds if we have markers
		if (markers.length > 0 && map && leaflet) {
			const group = leaflet.featureGroup(markers);
			map.fitBounds(group.getBounds().pad(0.1));
		}
	}

	$effect(() => {
		// Re-render markers and territories when standorte or serviceId change
		mappableStandorte;
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
			fetchDrivingTimeTerritories();
		}
	});

	onDestroy(() => {
		territoryRects.forEach((r) => r.remove());
		borderLines.forEach((l) => l.remove());
		markers.forEach((m) => m.remove());
		map?.remove();
	});
</script>

<div class="relative z-0 w-full h-full min-h-[500px]">
	<div bind:this={mapContainer} class="w-full h-full"></div>

	{#if loadingTerritories}
		<div class="absolute top-3 left-3 bg-white/95 px-4 py-2 rounded-lg shadow-lg z-[1000] flex items-center gap-3">
			<div class="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
			<span class="text-sm font-medium text-gray-700">
				Lade Gebiete... {loadingProgress}%
			</span>
		</div>
	{/if}
</div>
