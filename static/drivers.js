const API = window.location.origin;

console.log('=== DRIVERS.JS ZAŁADOWANY ===');
console.log('API URL:', API);

// Ustaw dzisiejszą datę
const today = new Date().toISOString().split('T')[0];
document.getElementById('dateFilter').value = today;

// Załaduj listę kierowców do filtra
async function loadDriversFilter() {
  try {
    const res = await fetch(`${API}/api/drivers`);
    const drivers = await res.json();
    const activeDrivers = drivers.filter(d => d.active !== false);

    const select = document.getElementById('driverFilter');
    select.innerHTML = '<option value="">Wszyscy kierowcy</option>' +
      activeDrivers.map(d => `<option value="${d.id}">${d.full_name}</option>`).join('');
  } catch (err) {
    console.error('Błąd ładowania kierowców:', err);
  }
}

// Oblicz całkowity dystans dla tras kierowcy
function calculateTotalDistance(routes) {
  console.log('\n=== CALCULATE TOTAL DISTANCE ===');
  console.log('Liczba tras:', routes?.length);

  if (!routes || routes.length === 0) {
    console.log('Brak tras - zwracam 0');
    return 0;
  }

  // Pokaż przykładową trasę
  console.log('Przykładowa trasa (pierwsza):', routes[0]);
  console.log('Wszystkie klucze w trasie:', Object.keys(routes[0]));

  let totalDistance = 0;

  // Sortuj trasy według czasu rozpoczęcia
  const sortedRoutes = [...routes].sort((a, b) =>
    new Date(a.starts_at) - new Date(b.starts_at)
  );

  // Oblicz dystans dla każdej trasy
  for (let i = 0; i < sortedRoutes.length; i++) {
    const route = sortedRoutes[i];

    console.log(`\n--- Trasa ${i + 1} ---`);
    console.log('Klient:', route.client_name);
    console.log('Od:', route.place_from, 'Do:', route.place_to);
    console.log('route.distance_km:', route.distance_km);
    console.log('route.distance_km type:', typeof route.distance_km);
    console.log('Współrzędne GPS:', {
      from_lat: route.from_latitude,
      from_lon: route.from_longitude,
      to_lat: route.to_latitude,
      to_lon: route.to_longitude,
      pickup_lat: route.pickup_latitude,
      pickup_lon: route.pickup_longitude,
      dropoff_lat: route.dropoff_latitude,
      dropoff_lon: route.dropoff_longitude
    });

    // Jeśli trasa ma podany dystans, użyj go
    if (route.distance_km && parseFloat(route.distance_km) > 0) {
      const dist = parseFloat(route.distance_km);
      console.log(`✓ Użyto distance_km: ${dist} km`);
      totalDistance += dist;
    } else {
      console.log('× Brak distance_km - próbuję obliczyć z GPS');

      // W przeciwnym razie oblicz z GPS
      const startLat = route.from_latitude || route.pickup_latitude;
      const startLon = route.from_longitude || route.pickup_longitude;
      const endLat = route.to_latitude || route.dropoff_latitude;
      const endLon = route.to_longitude || route.dropoff_longitude;

      console.log('Wybrane punkty GPS:', { startLat, startLon, endLat, endLon });

      if (startLat && startLon && endLat && endLon) {
        const distance = calculateDistanceGPS(startLat, startLon, endLat, endLon);
        console.log(`✓ Obliczono z GPS: ${distance.toFixed(2)} km`);
        totalDistance += distance;
      } else {
        console.log('× Brak kompletnych współrzędnych GPS - dystans = 0');
      }
    }

    // Dodaj dystans do następnej trasy (przejazd między trasami)
    if (i < sortedRoutes.length - 1) {
      const next = sortedRoutes[i + 1];

      const currentEndLat = route.to_latitude || route.dropoff_latitude;
      const currentEndLon = route.to_longitude || route.dropoff_longitude;
      const nextStartLat = next.from_latitude || next.pickup_latitude;
      const nextStartLon = next.from_longitude || next.pickup_longitude;

      if (currentEndLat && currentEndLon && nextStartLat && nextStartLon) {
        const distance = calculateDistanceGPS(
          currentEndLat, currentEndLon,
          nextStartLat, nextStartLon
        );
        console.log(`→ Dojazd do następnej trasy: ${distance.toFixed(2)} km`);
        totalDistance += distance;
      } else {
        console.log('→ Brak GPS dla dojazdu między trasami');
      }
    }
  }

  console.log(`\n=== PODSUMOWANIE ===`);
  console.log(`Całkowity dystans: ${totalDistance.toFixed(2)} km`);
  console.log('===================\n');
  return totalDistance;
}

// Oblicz dystans między dwoma punktami GPS (wzór Haversine)
function calculateDistanceGPS(lat1, lon1, lat2, lon2) {
  const R = 6371; // Promień Ziemi w km
  const dLat = toRadians(lat2 - lat1);
  const dLon = toRadians(lon2 - lon1);

  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(toRadians(lat1)) * Math.cos(toRadians(lat2)) *
    Math.sin(dLon / 2) * Math.sin(dLon / 2);

  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c; // Dystans w km
}

function toRadians(degrees) {
  return degrees * (Math.PI / 180);
}

// Załaduj dane kierowców z trasami
async function loadDriversSchedule() {
  const driverId = document.getElementById('driverFilter').value;
  const date = document.getElementById('dateFilter').value;
  const status = document.getElementById('statusFilter').value;

  const container = document.getElementById('driversContainer');
  container.innerHTML = '<div class="col-12 text-center py-5"><div class="spinner-border"></div><p class="text-muted mt-2">Ładowanie tras...</p></div>';

  console.log('=== ŁADOWANIE TRAS ===');
  console.log('Driver ID:', driverId);
  console.log('Date:', date);
  console.log('Status:', status);

  try {
    let drivers = [];

    if (driverId) {
      // Jeden kierowca - pobierz schedule i dane z filtra
      const url = `${API}/api/drivers/${driverId}/schedule?date=${date}`;
      console.log('Fetching:', url);

      const routesRes = await fetch(url);
      console.log('Response status:', routesRes.status);

      if (!routesRes.ok) {
        throw new Error(`HTTP ${routesRes.status}: ${routesRes.statusText}`);
      }

      const routes = await routesRes.json();
      console.log('Routes received:', routes);
      console.log('Number of routes:', routes.length);

      // Pobierz dane kierowcy z listy wszystkich
      const allRes = await fetch(`${API}/api/drivers`);
      const allDrivers = await allRes.json();
      const driverData = allDrivers.find(d => d.id == driverId);

      if (driverData) {
        drivers = [{...driverData, routes}];
      }
    } else {
      // Wszyscy kierowcy
      console.log('Fetching all drivers...');
      const res = await fetch(`${API}/api/drivers`);
      console.log('Drivers response status:', res.status);

      const allDrivers = await res.json();
      console.log('Total drivers:', allDrivers.length);

      // Pobierz trasy równolegle dla wszystkich kierowców
      const promises = allDrivers
        .filter(d => d.active !== false)
        .map(async driver => {
          try {
            const url = `${API}/api/drivers/${driver.id}/schedule?date=${date}`;
            console.log(`Fetching routes for ${driver.full_name}:`, url);

            const routesRes = await fetch(url);

            if (!routesRes.ok) {
              console.error(`Error for driver ${driver.id}:`, routesRes.status);
              return {...driver, routes: []};
            }

            const routes = await routesRes.json();
            console.log(`Routes for ${driver.full_name}:`, routes.length);

            return {...driver, routes};
          } catch (err) {
            console.error(`Błąd pobierania tras dla kierowcy ${driver.id}:`, err);
            return {...driver, routes: []};
          }
        });

      drivers = await Promise.all(promises);
    }

    console.log('=== DANE KIEROWCÓW ===');
    console.log('Total drivers with data:', drivers.length);
    drivers.forEach(d => {
      console.log(`${d.full_name}: ${d.routes?.length || 0} routes`);
    });

    // Filtruj po statusie
    if (status) {
      drivers.forEach(d => {
        const beforeFilter = d.routes.length;
        d.routes = d.routes.filter(r => r.status === status);
        console.log(`${d.full_name}: ${beforeFilter} -> ${d.routes.length} (filtered by status: ${status})`);
      });
    }

    // Renderuj
    renderDrivers(drivers);

  } catch (err) {
    console.error('=== BŁĄD ===');
    console.error('Error:', err);
    console.error('Stack:', err.stack);
    container.innerHTML = `
      <div class="col-12">
        <div class="alert alert-danger">
          <h5><i class="bi bi-exclamation-triangle"></i> Błąd ładowania danych</h5>
          <p><strong>Komunikat:</strong> ${err.message}</p>
          <hr>
          <p class="mb-0"><strong>Sprawdź:</strong></p>
          <ul class="mb-0">
            <li>Czy backend działa (Flask)?</li>
            <li>Czy endpoint <code>/api/drivers/${driverId || '{id}'}/schedule?date=${date}</code> istnieje?</li>
            <li>Czy endpoint <code>/api/drivers</code> istnieje?</li>
          </ul>
        </div>
      </div>`;
  }
}

function renderDrivers(drivers) {
  const container = document.getElementById('driversContainer');

  // Filtruj tylko kierowców z trasami
  const driversWithRoutes = drivers.filter(d => d.routes && d.routes.length > 0);

  if (driversWithRoutes.length === 0) {
    container.innerHTML = `
      <div class="col-12 text-center py-5">
        <i class="bi bi-inbox display-1 text-muted"></i>
        <p class="text-muted mt-3">Brak tras dla wybranych kryteriów</p>
      </div>`;
    return;
  }

  container.innerHTML = driversWithRoutes.map(driver => {
    // Oblicz całkowity czas
    const totalTime = driver.routes.reduce((sum, r) => {
      const start = new Date(r.starts_at);
      const end = new Date(r.ends_at);
      return sum + (end - start) / 60000; // w minutach
    }, 0);

    // Oblicz całkowity dystans (z trasami + między trasami)
    const totalDistance = calculateTotalDistance(driver.routes);

    // Statystyki tras
    const completedRoutes = driver.routes.filter(r => r.status === 'done').length;
    const pickups = driver.routes.filter(r => r.kind === 'pickup').length;
    const dropoffs = driver.routes.filter(r => r.kind === 'dropoff').length;

    // Pierwsza i ostatnia trasa
    const sortedRoutes = [...driver.routes].sort((a, b) =>
      new Date(a.starts_at) - new Date(b.starts_at)
    );
    const firstRoute = sortedRoutes[0];
    const lastRoute = sortedRoutes[sortedRoutes.length - 1];

    return `
      <div class="col-md-6 col-lg-4">
        <div class="card driver-card h-100 shadow-sm" onclick="showDriverDetails(${driver.id}, '${driver.full_name}')">
          <div class="card-header bg-primary text-white">
            <div class="d-flex justify-content-between align-items-center">
              <div>
                <i class="bi bi-person-circle me-2"></i>
                <strong>${driver.full_name}</strong>
              </div>
              <span class="badge bg-light text-primary">${driver.routes.length} tras${driver.routes.length === 1 ? 'a' : driver.routes.length < 5 ? 'y' : ''}</span>
            </div>
          </div>

          <div class="card-body">
            <!-- Statystyki w kafelkach -->
            <div class="row g-2 mb-3">
              <div class="col-6">
                <div class="text-center p-2 bg-light rounded">
                  <div class="small text-muted">Dystans</div>
                  <div class="h5 mb-0 text-primary">
                    <i class="bi bi-signpost-2"></i>
                    ${totalDistance.toFixed(1)} km
                  </div>
                </div>
              </div>
              <div class="col-6">
                <div class="text-center p-2 bg-light rounded">
                  <div class="small text-muted">Czas jazdy</div>
                  <div class="h5 mb-0 text-success">
                    <i class="bi bi-clock"></i>
                    ${Math.floor(totalTime / 60)}h ${Math.round(totalTime % 60)}m
                  </div>
                </div>
              </div>
              <div class="col-6">
                <div class="text-center p-2 bg-light rounded">
                  <div class="small text-muted">Odbiory</div>
                  <div class="fw-bold text-info">
                    <i class="bi bi-arrow-up-circle"></i> ${pickups}
                  </div>
                </div>
              </div>
              <div class="col-6">
                <div class="text-center p-2 bg-light rounded">
                  <div class="small text-muted">Dowozy</div>
                  <div class="fw-bold text-secondary">
                    <i class="bi bi-arrow-down-circle"></i> ${dropoffs}
                  </div>
                </div>
              </div>
            </div>

            <!-- Harmonogram (pierwsza i ostatnia trasa) -->
            ${firstRoute && lastRoute ? `
              <div class="mb-3 p-2 bg-light rounded">
                <div class="small text-muted mb-1">Harmonogram</div>
                <div class="d-flex justify-content-between align-items-center">
                  <span class="small">
                    <i class="bi bi-clock"></i>
                    ${formatTime(firstRoute.starts_at)}
                  </span>
                  <i class="bi bi-arrow-right text-muted"></i>
                  <span class="small">
                    <i class="bi bi-clock-fill"></i>
                    ${formatTime(lastRoute.ends_at)}
                  </span>
                </div>
              </div>
            ` : ''}

            <!-- Postęp -->
            <div class="mb-3">
              <div class="d-flex justify-content-between align-items-center mb-1">
                <small class="text-muted">Wykonane</small>
                <small class="text-muted">${completedRoutes}/${driver.routes.length}</small>
              </div>
              <div class="progress" style="height: 6px;">
                <div class="progress-bar bg-success"
                     style="width: ${(completedRoutes / driver.routes.length * 100)}%">
                </div>
              </div>
            </div>

            <!-- Podgląd tras (max 3) -->
            <div class="timeline">
              ${sortedRoutes.slice(0, 3).map(route => `
                <div class="route-item route-${route.kind} mb-2">
                  <div class="d-flex justify-content-between align-items-start">
                    <div class="flex-grow-1">
                      <div class="small text-muted">${formatTime(route.starts_at)}</div>
                      <div class="fw-semibold">${route.client_name || 'Klient'}</div>
                      <div class="small text-muted">
                        <i class="bi bi-geo-alt"></i>
                        ${route.place_from || '?'} → ${route.place_to || '?'}
                      </div>
                      ${route.distance_km ? `
                        <div class="small text-primary">
                          <i class="bi bi-speedometer2"></i> ${parseFloat(route.distance_km).toFixed(1)} km
                        </div>
                      ` : ''}
                    </div>
                    <span class="badge bg-${route.status === 'done' ? 'success' : route.status === 'cancelled' ? 'danger' : 'warning'} ms-2">
                      ${route.status === 'done' ? '✓' : route.status === 'cancelled' ? '✗' : '○'}
                    </span>
                  </div>
                </div>
              `).join('')}
              ${driver.routes.length > 3 ? `
                <div class="text-center small text-muted">
                  +${driver.routes.length - 3} więcej tras
                </div>
              ` : ''}
            </div>
          </div>

          <div class="card-footer bg-transparent">
            <button class="btn btn-sm btn-outline-primary w-100">
              <i class="bi bi-list-ul"></i> Szczegóły tras
            </button>
          </div>
        </div>
      </div>
    `;
  }).join('');
}

function formatTime(dateStr) {
  const d = new Date(dateStr);
  return d.toLocaleTimeString('pl-PL', {hour: '2-digit', minute: '2-digit'});
}

async function showDriverDetails(driverId, driverName) {
  const date = document.getElementById('dateFilter').value;
  const modal = new bootstrap.Modal(document.getElementById('routeModal'));
  const details = document.getElementById('routeDetails');

  details.innerHTML = '<div class="text-center py-4"><div class="spinner-border text-primary"></div><p class="text-muted mt-2">Ładowanie szczegółów...</p></div>';
  modal.show();

  try {
    const res = await fetch(`${API}/api/drivers/${driverId}/schedule?date=${date}`);
    const routes = await res.json();

    // Oblicz statystyki
    const totalDistance = calculateTotalDistance(routes);
    const totalTime = routes.reduce((sum, r) => {
      const start = new Date(r.starts_at);
      const end = new Date(r.ends_at);
      return sum + (end - start) / 60000;
    }, 0);
    const completedRoutes = routes.filter(r => r.status === 'done').length;

    // Sortuj trasy
    const sortedRoutes = [...routes].sort((a, b) =>
      new Date(a.starts_at) - new Date(b.starts_at)
    );

    details.innerHTML = `
      <div class="mb-4">
        <h6 class="text-primary mb-3">
          <i class="bi bi-person-circle"></i> ${driverName}
          <span class="text-muted small">- ${new Date(date).toLocaleDateString('pl-PL', {weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'})}</span>
        </h6>

        <!-- Podsumowanie -->
        <div class="row g-2 mb-4">
          <div class="col-md-3">
            <div class="text-center p-3 bg-light rounded">
              <div class="small text-muted">Liczba tras</div>
              <div class="h4 mb-0">${routes.length}</div>
            </div>
          </div>
          <div class="col-md-3">
            <div class="text-center p-3 bg-primary bg-opacity-10 rounded">
              <div class="small text-muted">Całkowity dystans</div>
              <div class="h4 mb-0 text-primary">${totalDistance.toFixed(1)} km</div>
            </div>
          </div>
          <div class="col-md-3">
            <div class="text-center p-3 bg-success bg-opacity-10 rounded">
              <div class="small text-muted">Czas jazdy</div>
              <div class="h4 mb-0 text-success">${Math.floor(totalTime / 60)}h ${Math.round(totalTime % 60)}m</div>
            </div>
          </div>
          <div class="col-md-3">
            <div class="text-center p-3 bg-light rounded">
              <div class="small text-muted">Wykonane</div>
              <div class="h4 mb-0">${completedRoutes}/${routes.length}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Lista wszystkich tras -->
      <h6 class="mb-3">Szczegółowy harmonogram</h6>
      <div class="timeline">
        ${sortedRoutes.map((route, index) => {
          const routeDistance = parseFloat(route.distance_km) || 0;

          // Oblicz dystans między trasami (jeśli jest następna trasa)
          let distanceBetween = 0;
          if (index < sortedRoutes.length - 1) {
            const nextRoute = sortedRoutes[index + 1];
            const currentEndLat = route.to_latitude || route.dropoff_latitude;
            const currentEndLon = route.to_longitude || route.dropoff_longitude;
            const nextStartLat = nextRoute.from_latitude || nextRoute.pickup_latitude;
            const nextStartLon = nextRoute.from_longitude || nextRoute.pickup_longitude;

            if (currentEndLat && currentEndLon && nextStartLat && nextStartLon) {
              distanceBetween = calculateDistanceGPS(
                currentEndLat, currentEndLon,
                nextStartLat, nextStartLon
              );
            }
          }

          return `
            <div class="route-item route-${route.kind} p-3 ${route.status === 'done' ? 'bg-success' : route.status === 'cancelled' ? 'bg-danger' : 'bg-light'} bg-opacity-10 rounded mb-3">
              <div class="d-flex justify-content-between align-items-start mb-2">
                <div>
                  <span class="badge bg-${route.kind === 'pickup' ? 'info' : 'secondary'} mb-2">
                    ${route.kind === 'pickup' ? 'ODBIÓR' : 'DOWÓZ'}
                  </span>
                  <h6 class="mb-1">${route.client_name || 'Klient'}</h6>
                </div>
                <span class="badge bg-${route.status === 'done' ? 'success' : route.status === 'cancelled' ? 'danger' : 'warning'}">
                  ${route.status === 'done' ? 'Wykonane' : route.status === 'cancelled' ? 'Anulowane' : 'Zaplanowane'}
                </span>
              </div>

              <div class="row g-2 small">
                <div class="col-md-6">
                  <i class="bi bi-clock"></i>
                  <strong>${formatTime(route.starts_at)}</strong> - ${formatTime(route.ends_at)}
                  <span class="text-muted">(${Math.round((new Date(route.ends_at) - new Date(route.starts_at)) / 60000)} min)</span>
                </div>
                <div class="col-md-6">
                  <i class="bi bi-speedometer2 text-primary"></i>
                  <strong class="text-primary">${routeDistance.toFixed(1)} km</strong>
                </div>
                <div class="col-12">
                  <i class="bi bi-geo-alt text-danger"></i>
                  <strong>${route.place_from || 'Start'}</strong>
                  <i class="bi bi-arrow-right mx-1"></i>
                  <strong>${route.place_to || 'Cel'}</strong>
                </div>
                ${route.vehicle_id ? `
                  <div class="col-md-6">
                    <i class="bi bi-car-front"></i> Pojazd #${route.vehicle_id}
                  </div>
                ` : ''}
                ${route.notes ? `
                  <div class="col-12">
                    <i class="bi bi-info-circle"></i> ${route.notes}
                  </div>
                ` : ''}
              </div>

              ${distanceBetween > 0 ? `
                <div class="mt-2 pt-2 border-top">
                  <small class="text-muted">
                    <i class="bi bi-arrow-down"></i>
                    Dojazd do następnej trasy: <strong>${distanceBetween.toFixed(1)} km</strong>
                  </small>
                </div>
              ` : ''}
            </div>
          `;
        }).join('')}
      </div>
    `;
  } catch (err) {
    console.error('Błąd pobierania szczegółów:', err);
    details.innerHTML = `<div class="alert alert-danger"><i class="bi bi-exclamation-triangle"></i> Błąd: ${err.message}</div>`;
  }
}

// Event listeners
document.getElementById('loadBtn').addEventListener('click', loadDriversSchedule);

// Inicjalizacja
loadDriversFilter();

loadDriversSchedule();
