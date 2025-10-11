import psycopg2
from psycopg2.extras import RealDictCursor
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import time

# Inicjalizacja geokodera
geolocator = Nominatim(user_agent="suo_app")


def get_coordinates(address):
    """Zamienia adres na współrzędne GPS"""
    if not address:
        return None, None

    try:
        # Dodaj ", Polska" dla lepszych wyników
        location = geolocator.geocode(address + ", Polska")
        if location:
            return location.latitude, location.longitude

        # Jeśli nie znaleziono, spróbuj bez ", Polska"
        location = geolocator.geocode(address)
        if location:
            return location.latitude, location.longitude
    except Exception as e:
        print(f"Błąd geokodowania '{address}': {e}")

    return None, None


def geocode_all_routes():
    """Geokoduje wszystkie adresy w schedule_slots"""
    conn = psycopg2.connect(
        host='localhost',
        port='5432',
        database='suo',
        user='postgres',
        password='EDUQ'
    )
    cur = conn.cursor(cursor_factory=RealDictCursor)

    # Pobierz wszystkie trasy bez współrzędnych
    cur.execute("""
        SELECT id, place_from, place_to, from_latitude, to_latitude
        FROM schedule_slots
        WHERE kind IN ('pickup', 'dropoff')
        AND (from_latitude IS NULL OR to_latitude IS NULL)
    """)

    routes = cur.fetchall()
    total = len(routes)
    print(f"Znaleziono {total} tras do geokodowania\n")

    for i, route in enumerate(routes, 1):
        route_id = route['id']
        place_from = route['place_from']
        place_to = route['place_to']

        print(f"[{i}/{total}] Trasa #{route_id}: {place_from} → {place_to}")

        # Geokoduj adres początkowy
        if not route['from_latitude'] and place_from:
            lat, lon = get_coordinates(place_from)
            if lat and lon:
                cur.execute("""
                    UPDATE schedule_slots 
                    SET from_latitude = %s, from_longitude = %s
                    WHERE id = %s
                """, (lat, lon, route_id))
                print(f"  ✓ from: ({lat}, {lon})")
            else:
                print(f"  ✗ Nie znaleziono współrzędnych dla: {place_from}")

            # Opóźnienie aby nie przekroczyć limitu API (1 request/sec)
            time.sleep(1.5)

        # Geokoduj adres końcowy
        if not route['to_latitude'] and place_to:
            lat, lon = get_coordinates(place_to)
            if lat and lon:
                cur.execute("""
                    UPDATE schedule_slots 
                    SET to_latitude = %s, to_longitude = %s
                    WHERE id = %s
                """, (lat, lon, route_id))
                print(f"  ✓ to: ({lat}, {lon})")
            else:
                print(f"  ✗ Nie znaleziono współrzędnych dla: {place_to}")

            time.sleep(1.5)

        # Oblicz dystans jeśli mamy obie współrzędne
        cur.execute("""
            SELECT from_latitude, from_longitude, to_latitude, to_longitude
            FROM schedule_slots WHERE id = %s
        """, (route_id,))
        updated_route = cur.fetchone()

        if all([updated_route['from_latitude'], updated_route['from_longitude'],
                updated_route['to_latitude'], updated_route['to_longitude']]):
            distance = geodesic(
                (updated_route['from_latitude'], updated_route['from_longitude']),
                (updated_route['to_latitude'], updated_route['to_longitude'])
            ).kilometers

            cur.execute("""
                UPDATE schedule_slots 
                SET distance_km = %s
                WHERE id = %s
            """, (round(distance, 2), route_id))
            print(f"  ✓ Dystans: {distance:.2f} km")

        conn.commit()
        print()

    print("Geokodowanie zakończone!")
    cur.close()
    conn.close()


if __name__ == '__main__':
    geocode_all_routes()