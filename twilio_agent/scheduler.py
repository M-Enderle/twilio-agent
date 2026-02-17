"""
Background scheduler for periodic tasks.

This module handles scheduled background tasks such as:
- Daily territory border calculation at 4:00 AM
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from twilio_agent.actions.redis_actions import redis
from twilio_agent.settings import settings

logger = logging.getLogger(__name__)

# Grid configuration (must match frontend settings)
GRID_SIZE = 32
BATCH_SIZE = 20
MAX_DISTANCE_KM = 50

# Create scheduler instance
scheduler = AsyncIOScheduler()


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate haversine distance between two points in kilometers."""
    import math

    R = 6371  # Earth radius in km
    dLat = (lat2 - lat1) * math.pi / 180
    dLng = (lng2 - lng1) * math.pi / 180
    a = (
        math.sin(dLat / 2) ** 2
        + math.cos(lat1 * math.pi / 180)
        * math.cos(lat2 * math.pi / 180)
        * math.sin(dLng / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_bounds(
    locations: list[Any],
) -> dict[str, float]:
    """Compute dynamic bounds from locations with 50km padding."""
    lats = [loc.latitude for loc in locations if loc.latitude]
    lngs = [loc.longitude for loc in locations if loc.longitude]

    if not lats or not lngs:
        # Fallback to Germany if no locations
        return {"minLat": 47.2, "maxLat": 55.0, "minLng": 5.8, "maxLng": 15.0}

    # ~50km in degrees (rough approximation)
    lat_padding = MAX_DISTANCE_KM / 111  # 1 degree lat ≈ 111km
    avg_lat = (min(lats) + max(lats)) / 2
    lng_padding = MAX_DISTANCE_KM / (111 * abs(math.cos(avg_lat * math.pi / 180)))

    return {
        "minLat": min(lats) - lat_padding,
        "maxLat": max(lats) + lat_padding,
        "minLng": min(lngs) - lng_padding,
        "maxLng": max(lngs) + lng_padding,
    }


def is_point_relevant(lat: float, lng: float, locations: list[Any]) -> bool:
    """Check if a grid point is within MAX_DISTANCE_KM of any location."""
    for loc in locations:
        if loc.latitude and loc.longitude:
            dist = haversine_km(lat, lng, loc.latitude, loc.longitude)
            if dist <= MAX_DISTANCE_KM:
                return True
    return False


async def calculate_service_territories(service_id: str) -> None:
    """
    Calculate territory borders for a single service using OSRM API.

    This function:
    1. Retrieves all locations for the service
    2. Generates a grid of points
    3. Queries OSRM to find which location is closest (by drive time) to each point
    4. Saves the results to Redis cache
    """
    import math

    logger.info(f"Starting territory calculation for service: {service_id}")

    try:
        # Get service locations
        locations = settings.service(service_id).locations
        mappable_locations = [
            loc for loc in locations if loc.latitude and loc.longitude
        ]

        if len(mappable_locations) < 2:
            logger.info(
                f"Service {service_id} has fewer than 2 locations with coordinates, skipping territory calculation"
            )
            return

        logger.info(
            f"Service {service_id}: Found {len(mappable_locations)} mappable locations"
        )

        # Compute dynamic bounds from contact locations + 50km padding
        bounds = compute_bounds(mappable_locations)
        logger.info(
            f"Service {service_id}: Dynamic bounds: lat {bounds['minLat']:.2f}-{bounds['maxLat']:.2f}, "
            f"lng {bounds['minLng']:.2f}-{bounds['maxLng']:.2f}"
        )

        # Generate grid points within bounds
        all_grid_points = []
        for i in range(GRID_SIZE):
            for j in range(GRID_SIZE):
                lat = bounds["minLat"] + (i / (GRID_SIZE - 1)) * (
                    bounds["maxLat"] - bounds["minLat"]
                )
                lng = bounds["minLng"] + (j / (GRID_SIZE - 1)) * (
                    bounds["maxLng"] - bounds["minLng"]
                )
                all_grid_points.append({"lat": lat, "lng": lng})

        # Filter to only points within MAX_DISTANCE_KM of any location
        grid_points = [
            p
            for p in all_grid_points
            if is_point_relevant(p["lat"], p["lng"], mappable_locations)
        ]
        logger.info(
            f"Service {service_id}: Using {len(grid_points)} grid points (filtered from {len(all_grid_points)})"
        )

        # Location coordinates for OSRM
        location_coords = [
            f"{loc.longitude},{loc.latitude}" for loc in mappable_locations
        ]
        results = []

        # Process in batches
        async with httpx.AsyncClient(timeout=30.0) as client:
            for batch_start in range(0, len(grid_points), BATCH_SIZE):
                batch_points = grid_points[batch_start : batch_start + BATCH_SIZE]

                # Build OSRM request
                batch_coords = [
                    f"{p['lng']},{p['lat']}" for p in batch_points
                ] + location_coords
                batch_coords_str = ";".join(batch_coords)

                sources = ";".join(str(i) for i in range(len(batch_points)))
                destinations = ";".join(
                    str(len(batch_points) + i) for i in range(len(location_coords))
                )

                try:
                    response = await client.get(
                        f"https://router.project-osrm.org/table/v1/driving/{batch_coords_str}",
                        params={"sources": sources, "destinations": destinations},
                    )
                    data = response.json()

                    if data.get("code") == "Ok":
                        for i, point in enumerate(batch_points):
                            durations = data["durations"][i]
                            min_index = 0
                            min_time = durations[0] if durations[0] is not None else float("inf")

                            for j, time in enumerate(durations):
                                if time is not None and time < min_time:
                                    min_time = time
                                    min_index = j

                            results.append({**point, "contactIndex": min_index})

                except Exception as e:
                    logger.error(f"Service {service_id}: OSRM batch failed: {e}")

                # Log progress
                if (batch_start // BATCH_SIZE + 1) % 5 == 0:
                    logger.info(
                        f"Service {service_id}: Progress {len(results)}/{len(grid_points)} points"
                    )

                # Small delay between batches to avoid rate limiting
                await asyncio.sleep(0.1)

        # Compute locations hash for cache invalidation
        coords_sorted = sorted(
            [
                f"{loc.latitude:.6f},{loc.longitude:.6f}"
                for loc in mappable_locations
            ]
        )
        locations_hash = "|".join(coords_sorted)[:12]

        # Save to Redis cache
        cache_key = f"notdienststation:{service_id}:territories"
        cache_data = {
            "grid": results,
            "locations_hash": locations_hash,
            "computed_at": datetime.utcnow().isoformat(),
            "is_partial": False,
            "total_points": len(grid_points),
            "bounds": bounds,
        }

        redis.set(cache_key, json.dumps(cache_data))

        # Clean up partial cache
        partial_key = f"notdienststation:{service_id}:territories:partial"
        redis.delete(partial_key)

        logger.info(
            f"Service {service_id}: Territory calculation completed. {len(results)} points saved to cache."
        )

    except Exception as e:
        logger.error(f"Service {service_id}: Territory calculation failed: {e}", exc_info=True)


async def calculate_all_territories() -> None:
    """
    Calculate territory borders for all services.

    This is the scheduled task that runs daily at 4:00 AM.
    """
    logger.info("Starting scheduled territory calculation for all services")

    # Get all service IDs from settings
    service_ids = ["schluessel-allgaeu", "notdienst-schluessel", "notdienst-abschlepp"]

    for service_id in service_ids:
        try:
            await calculate_service_territories(service_id)
        except Exception as e:
            logger.error(f"Failed to calculate territories for {service_id}: {e}", exc_info=True)

    logger.info("Scheduled territory calculation completed for all services")


def start_scheduler() -> None:
    """
    Start the background scheduler.

    This should be called when the FastAPI app starts.
    """
    # Schedule territory calculation daily at 4:00 AM
    scheduler.add_job(
        calculate_all_territories,
        trigger=CronTrigger(hour=4, minute=0),
        id="daily_territory_calculation",
        name="Calculate territory borders for all services",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Background scheduler started. Territory calculation scheduled for 4:00 AM daily.")


def stop_scheduler() -> None:
    """
    Stop the background scheduler.

    This should be called when the FastAPI app shuts down.
    """
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Background scheduler stopped.")
