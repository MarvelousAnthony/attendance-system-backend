import math

def calculate_haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great circle distance between two points on the Earth's surface
    (specified in decimal degrees) in meters.
    
    Uses a pure mathematical implementation of the Haversine formula.
    """
    # Convert decimal degrees to radians
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    # Differences in coordinates
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    # Haversine calculation
    a = math.sin(dlat / 2.0)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2.0)**2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    
    # Earth's radius in meters (6,371 km)
    earth_radius_meters = 6371000.0
    
    return earth_radius_meters * c
