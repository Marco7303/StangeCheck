import { useEffect, useMemo, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import { listBeerSpots } from "./lib/mockDb";

const numberFormat = new Intl.NumberFormat("de-CH", {
  style: "currency",
  currency: "CHF",
  minimumFractionDigits: 2,
});

const swissCenter = { lat: 46.8182, lng: 8.2275 };
const defaultZoom = 8;
const swissBounds = [
  [5.95, 45.75],
  [10.65, 47.95],
];
const mapboxAccessToken = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN;

function App() {
  const [theme, setTheme] = useState(() => {
    const storedTheme = window.localStorage.getItem("stange-check-theme");
    if (storedTheme) {
      return storedTheme;
    }

    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  });
  const [spots, setSpots] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [loading, setLoading] = useState(true);
  const [visibleIds, setVisibleIds] = useState([]);
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState("");
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const markersRef = useRef(new Map());
  const popupRef = useRef(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("stange-check-theme", theme);
  }, [theme]);

  useEffect(() => {
    let active = true;

    listBeerSpots().then((rows) => {
      if (!active) {
        return;
      }

      setSpots(rows);
      setSelectedId(rows[0]?.id ?? null);
      setLoading(false);
    });

    return () => {
      active = false;
    };
  }, []);

  const visibleSpots = useMemo(() => {
    return spots
      .filter((spot) => visibleIds.includes(spot.id))
      .sort((a, b) => a.price - b.price);
  }, [spots, visibleIds]);

  const selectedSpot = useMemo(() => {
    return (
      spots.find((spot) => spot.id === selectedId) ??
      visibleSpots[0] ??
      spots[0] ??
      null
    );
  }, [selectedId, spots, visibleSpots]);

  const cheapestVisible = visibleSpots[0] ?? null;
  const averagePrice =
    visibleSpots.reduce((total, spot) => total + spot.price, 0) /
      (visibleSpots.length || 1);

  useEffect(() => {
    if (!spots.length) {
      return;
    }

    if (!mapboxAccessToken) {
      setMapError("Map setup required.");
      setVisibleIds(spots.map((spot) => spot.id));
      return;
    }

    let cancelled = false;

    function initializeMap() {
      try {
        setMapError("");
        mapboxgl.accessToken = mapboxAccessToken;

        if (cancelled || !mapRef.current || mapInstanceRef.current) {
          return;
        }

        const map = new mapboxgl.Map({
          container: mapRef.current,
          style: "mapbox://styles/mapbox/standard",
          center: [swissCenter.lng, swissCenter.lat],
          zoom: defaultZoom,
          maxBounds: swissBounds,
          attributionControl: false,
        });

        map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "top-right");
        mapInstanceRef.current = map;
        popupRef.current = new mapboxgl.Popup({
          closeButton: false,
          closeOnClick: false,
          offset: 18,
          className: "stange-popup",
        });

        const syncVisibleSpots = () => {
          const bounds = map.getBounds();

          if (!bounds) {
            return;
          }

          const nextVisibleIds = spots
            .filter((spot) => bounds.contains([spot.lng, spot.lat]))
            .map((spot) => spot.id);

          setVisibleIds(nextVisibleIds);
        };

        spots.forEach((spot) => {
          const markerNode = document.createElement("button");
          markerNode.type = "button";
          markerNode.className = "custom-marker";
          markerNode.innerHTML = `
            <span>${spot.city}</span>
            <strong>${numberFormat.format(spot.price)}</strong>
          `;

          const marker = new mapboxgl.Marker({
            element: markerNode,
            anchor: "bottom",
          })
            .setLngLat([spot.lng, spot.lat])
            .addTo(map);

          markerNode.addEventListener("click", () => {
            setSelectedId(spot.id);
          });

          markersRef.current.set(spot.id, { marker, node: markerNode });
        });

        map.on("load", () => {
          if (cancelled) {
            return;
          }

          syncVisibleSpots();
          setMapReady(true);
        });

        map.on("moveend", syncVisibleSpots);
        map.on("zoomend", syncVisibleSpots);
      } catch (error) {
        if (cancelled) {
          return;
        }

        setMapError(error instanceof Error ? error.message : "Map unavailable.");
        setVisibleIds(spots.map((spot) => spot.id));
      }
    }

    initializeMap();

    return () => {
      cancelled = true;
      popupRef.current?.remove();
      popupRef.current = null;
      markersRef.current.forEach(({ marker }) => marker.remove());
      markersRef.current.clear();
      mapInstanceRef.current?.remove();
      mapInstanceRef.current = null;
    };
  }, [spots]);

  useEffect(() => {
    markersRef.current.forEach(({ marker, node }, markerId) => {
      node.classList.toggle("is-selected", markerId === selectedSpot?.id);
      node.classList.toggle("is-visible", visibleIds.includes(markerId));
      marker.getElement().style.zIndex = markerId === selectedSpot?.id ? "1000" : "100";
    });

    if (!selectedSpot || !mapInstanceRef.current) {
      return;
    }

    mapInstanceRef.current.easeTo({
      center: [selectedSpot.lng, selectedSpot.lat],
      duration: 700,
    });

    popupRef.current?.setHTML(`
      <div class="info-window">
        <strong>${selectedSpot.name}</strong>
        <span>${numberFormat.format(selectedSpot.price)} · ${selectedSpot.beer}</span>
      </div>
    `);

    popupRef.current
      ?.setLngLat([selectedSpot.lng, selectedSpot.lat])
      .addTo(mapInstanceRef.current);
  }, [selectedSpot, visibleIds]);

  function resetMapView() {
    if (!mapInstanceRef.current) {
      return;
    }

    mapInstanceRef.current.fitBounds(swissBounds, {
      padding: 48,
      duration: 700,
    });
  }

  return (
    <div className="app-shell">
      <div className="ambient ambient-a" />
      <div className="ambient ambient-b" />

      <header className="topbar">
        <div>
          <p className="eyebrow">Switzerland’s beer price radar</p>
          <h1>Stange Check</h1>
        </div>

        <div className="topbar-actions">
          <div className="status-pill">
            <span className="status-dot" />
            Mapbox live
          </div>
          <button
            className="theme-toggle"
            type="button"
            onClick={() =>
              setTheme((currentTheme) =>
                currentTheme === "dark" ? "light" : "dark",
              )
            }
          >
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </button>
        </div>
      </header>

      <main className="layout">
        <section className="summary-bar">
          <div className="summary-item">
            <span>Visible</span>
            <strong>{visibleSpots.length}</strong>
          </div>
          <div className="summary-item">
            <span>Cheapest</span>
            <strong>
              {cheapestVisible ? numberFormat.format(cheapestVisible.price) : "None"}
            </strong>
          </div>
          <div className="summary-item">
            <span>Average</span>
            <strong>{numberFormat.format(averagePrice || 0)}</strong>
          </div>
        </section>

        <section
          className={`experience-grid ${sidebarOpen ? "" : "is-sidebar-hidden"}`.trim()}
        >
          <div className="map-card">
            <div className="map-toolbar">
              <div className="map-toolbar-group">
                <button type="button" onClick={resetMapView}>
                  Reset view
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (selectedSpot && mapInstanceRef.current) {
                      mapInstanceRef.current.easeTo({
                        center: [selectedSpot.lng, selectedSpot.lat],
                        zoom: 14,
                        duration: 700,
                      });
                    }
                  }}
                >
                  Focus selected
                </button>
              </div>

              <div className="map-note">
                Ranking updates from the current map viewport.
              </div>

              <button
                type="button"
                className="drawer-toggle"
                onClick={() => setSidebarOpen((currentState) => !currentState)}
              >
                {sidebarOpen ? "Hide ranking" : "Show ranking"}
              </button>
            </div>

            <div className="map-stage">
              <div ref={mapRef} className="map-canvas" />

              {!mapboxAccessToken || mapError ? (
                <div className="map-fallback">
                  <span className="overlay-label">Map</span>
                  <strong>{mapError || "Unavailable"}</strong>
                  <p>
                    Add `VITE_MAPBOX_ACCESS_TOKEN` in `.env` to enable the live map.
                  </p>
                </div>
              ) : null}

              <div className="map-overlay top-left">
                <span className="overlay-label">Viewport ranking</span>
                <strong>{mapReady ? "Live on map move" : "Loading map"}</strong>
              </div>

              <div className="map-overlay bottom-right">
                <span className="overlay-label">Selected</span>
                <strong>{selectedSpot ? selectedSpot.city : "None"}</strong>
              </div>
            </div>
          </div>

          <aside className={`sidebar ${sidebarOpen ? "is-open" : "is-collapsed"}`}>
            <div className="sidebar-header">
              <div>
                <p className="eyebrow">Live ranking in view</p>
                <h3>Cheapest first</h3>
              </div>
              <span className="sidebar-count">{visibleSpots.length}</span>
            </div>

            {selectedSpot && (
              <div className="feature-card">
                <p className="eyebrow">Selected venue</p>
                <h4>{selectedSpot.name}</h4>
                <div className="feature-price">{numberFormat.format(selectedSpot.price)}</div>
                <p>
                  {selectedSpot.address}, {selectedSpot.city}
                </p>
                <p>{selectedSpot.vibe}</p>
              </div>
            )}

            {loading ? (
              <div className="loading-card">Loading venues…</div>
            ) : visibleSpots.length === 0 ? (
              <div className="loading-card">
                No bars in the current viewport. Pan or zoom out to widen the search.
              </div>
            ) : (
              <div className="results-list">
                {visibleSpots
                  .filter((spot) => spot.id !== selectedSpot?.id)
                  .map((spot, index) => (
                  <button
                    key={spot.id}
                    type="button"
                    className={`result-card ${selectedSpot?.id === spot.id ? "is-selected" : ""}`}
                    onClick={() => setSelectedId(spot.id)}
                  >
                    <div className="result-rank">#{index + 1}</div>
                    <div className="result-main">
                      <div className="result-topline">
                        <h4>{spot.name}</h4>
                        <strong>{numberFormat.format(spot.price)}</strong>
                      </div>
                      <p>
                        {spot.city}, {spot.canton} · {spot.beer}
                      </p>
                      <small>{spot.vibe}</small>
                    </div>
                  </button>
                  ))}
              </div>
            )}

          </aside>
        </section>
      </main>
    </div>
  );
}

export default App;
