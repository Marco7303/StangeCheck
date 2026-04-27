import {
  useDeferredValue,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import mapboxgl from "mapbox-gl";
import { listBeerSpots } from "./lib/mockDb";

const numberFormat = new Intl.NumberFormat("de-CH", {
  style: "currency",
  currency: "CHF",
  minimumFractionDigits: 2,
});

const swissBounds = [
  [5.95, 45.75],
  [10.65, 47.95],
];

const mapboxAccessToken = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN;

function arraysEqual(left, right) {
  if (left.length !== right.length) {
    return false;
  }

  return left.every((value, index) => value === right[index]);
}

function matchesQuery(spot, query) {
  const haystack = [
    spot.name,
    spot.city,
    spot.canton,
    spot.beer,
    spot.address,
    spot.vibe,
  ]
    .join(" ")
    .toLowerCase();

  return haystack.includes(query);
}

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
  const [searchValue, setSearchValue] = useState("");
  const deferredSearch = useDeferredValue(searchValue);
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const markersRef = useRef(new Map());
  const popupRef = useRef(null);
  const visibleIdsRef = useRef([]);

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
      .sort((left, right) => left.price - right.price);
  }, [spots, visibleIds]);

  const normalizedQuery = deferredSearch.trim().toLowerCase();

  const filteredVisibleSpots = useMemo(() => {
    if (!normalizedQuery) {
      return visibleSpots;
    }

    return visibleSpots.filter((spot) => matchesQuery(spot, normalizedQuery));
  }, [visibleSpots, normalizedQuery]);

  const selectedSpot = useMemo(() => {
    return spots.find((spot) => spot.id === selectedId) ?? null;
  }, [spots, selectedId]);

  const selectedVisibleSpot = useMemo(() => {
    return visibleSpots.find((spot) => spot.id === selectedId) ?? null;
  }, [visibleSpots, selectedId]);

  const cheapestVisible = filteredVisibleSpots[0] ?? null;
  const averageVisiblePrice =
    filteredVisibleSpots.reduce((total, spot) => total + spot.price, 0) /
      (filteredVisibleSpots.length || 1);
  const visibleCities = new Set(filteredVisibleSpots.map((spot) => spot.city)).size;

  function syncVisibleSpots(map) {
    const bounds = map.getBounds();

    if (!bounds) {
      return;
    }

    const nextVisibleIds = spots
      .filter((spot) => bounds.contains([spot.lng, spot.lat]))
      .map((spot) => spot.id)
      .sort();

    if (arraysEqual(visibleIdsRef.current, nextVisibleIds)) {
      return;
    }

    visibleIdsRef.current = nextVisibleIds;
    setVisibleIds(nextVisibleIds);
  }

  function focusSpot(spot, zoom = 13.2) {
    if (!spot || !mapInstanceRef.current) {
      return;
    }

    setSelectedId(spot.id);
    mapInstanceRef.current.easeTo({
      center: [spot.lng, spot.lat],
      zoom,
      duration: 700,
    });
  }

  function resetMapView() {
    if (!mapInstanceRef.current) {
      return;
    }

    mapInstanceRef.current.fitBounds(swissBounds, {
      padding: {
        top: 110,
        right: sidebarOpen ? 430 : 32,
        bottom: 42,
        left: 32,
      },
      duration: 700,
    });
  }

  function handleSearchSubmit(event) {
    event.preventDefault();

    if (filteredVisibleSpots[0]) {
      focusSpot(filteredVisibleSpots[0], 13.5);
    }
  }

  useEffect(() => {
    if (!spots.length) {
      return;
    }

    if (!mapboxAccessToken) {
      setMapError("Map setup required.");
      const allIds = spots.map((spot) => spot.id);
      visibleIdsRef.current = allIds;
      setVisibleIds(allIds);
      return;
    }

    let cancelled = false;

    try {
      setMapError("");
      mapboxgl.accessToken = mapboxAccessToken;

      if (cancelled || !mapRef.current || mapInstanceRef.current) {
        return undefined;
      }

      const map = new mapboxgl.Map({
        container: mapRef.current,
        style: "mapbox://styles/mapbox/standard",
        bounds: swissBounds,
        fitBoundsOptions: {
          padding: {
            top: 110,
            right: 430,
            bottom: 42,
            left: 32,
          },
        },
        maxBounds: swissBounds,
        attributionControl: false,
        pitch: 0,
        bearing: 0,
        config: {
          basemap: {
            lightPreset: theme === "dark" ? "night" : "day",
            showPointOfInterestLabels: false,
            showTransitLabels: false,
            show3dObjects: false,
          },
        },
      });

      map.dragRotate.disable();
      map.touchZoomRotate.disableRotation();
      map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "bottom-left");
      mapInstanceRef.current = map;
      popupRef.current = new mapboxgl.Popup({
        closeButton: false,
        closeOnClick: false,
        offset: 16,
        className: "stange-popup",
      });

      const updateVisibleSpots = () => syncVisibleSpots(map);

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

        map.resize();
        updateVisibleSpots();
        setMapReady(true);
      });

      map.on("move", updateVisibleSpots);
      map.on("moveend", updateVisibleSpots);
      map.on("error", (event) => {
        if (cancelled || mapReady) {
          return;
        }

        const message =
          event?.error instanceof Error
            ? event.error.message
            : "Map unavailable.";
        setMapError(message);
      });

      return () => {
        cancelled = true;
        popupRef.current?.remove();
        popupRef.current = null;
        markersRef.current.forEach(({ marker }) => marker.remove());
        markersRef.current.clear();
        map.remove();
        mapInstanceRef.current = null;
      };
    } catch (error) {
      if (!cancelled) {
        setMapError(error instanceof Error ? error.message : "Map unavailable.");
        const allIds = spots.map((spot) => spot.id);
        visibleIdsRef.current = allIds;
        setVisibleIds(allIds);
      }
    }

    return undefined;
  }, [spots]);

  useEffect(() => {
    if (!mapInstanceRef.current || !mapReady) {
      return;
    }

    mapInstanceRef.current.setConfigProperty(
      "basemap",
      "lightPreset",
      theme === "dark" ? "night" : "day",
    );
  }, [theme, mapReady]);

  useEffect(() => {
    markersRef.current.forEach(({ marker, node }, markerId) => {
      node.classList.toggle("is-selected", markerId === selectedVisibleSpot?.id);
      node.classList.toggle("is-visible", visibleIds.includes(markerId));
      marker.getElement().style.zIndex =
        markerId === selectedVisibleSpot?.id ? "1000" : "120";
    });
  }, [selectedVisibleSpot, visibleIds]);

  useEffect(() => {
    if (!selectedVisibleSpot || !mapInstanceRef.current || !popupRef.current) {
      popupRef.current?.remove();
      return;
    }

    popupRef.current.setHTML(`
      <div class="info-window">
        <strong>${selectedVisibleSpot.name}</strong>
        <span>${numberFormat.format(selectedVisibleSpot.price)} · ${selectedVisibleSpot.beer}</span>
      </div>
    `);

    popupRef.current
      .setLngLat([selectedVisibleSpot.lng, selectedVisibleSpot.lat])
      .addTo(mapInstanceRef.current);
  }, [selectedVisibleSpot]);

  useEffect(() => {
    if (!mapInstanceRef.current) {
      return;
    }

    const resizeMap = () => {
      mapInstanceRef.current?.resize();
    };

    const timeoutId = window.setTimeout(resizeMap, 220);
    window.addEventListener("resize", resizeMap);

    return () => {
      window.clearTimeout(timeoutId);
      window.removeEventListener("resize", resizeMap);
    };
  }, [sidebarOpen]);

  return (
    <div className="screen">
      <div ref={mapRef} className="map-canvas" />
      <div className="map-scrim" />

      <header className="floating-topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <span />
          </div>
          <div>
            <p className="brand-kicker">Switzerland</p>
            <h1>Stange Check</h1>
          </div>
        </div>

        <form className="search-shell" onSubmit={handleSearchSubmit}>
          <label className="search-label" htmlFor="venue-search">
            Search visible venues
          </label>
          <input
            id="venue-search"
            type="search"
            value={searchValue}
            onChange={(event) => setSearchValue(event.target.value)}
            placeholder="Search visible venues, cities, or beer names"
          />
        </form>

        <div className="topbar-actions">
          <button type="button" className="control-button" onClick={resetMapView}>
            Reset
          </button>
          <button
            type="button"
            className="control-button"
            onClick={() =>
              setTheme((currentTheme) =>
                currentTheme === "dark" ? "light" : "dark",
              )
            }
          >
            {theme === "dark" ? "Light" : "Dark"}
          </button>
          <button
            type="button"
            className="control-button is-primary"
            onClick={() => setSidebarOpen((currentState) => !currentState)}
          >
            {sidebarOpen ? "Hide list" : "Show list"}
          </button>
        </div>
      </header>

      <div className="floating-stats">
        <div className="stat-pill">
          <span>Visible</span>
          <strong>{filteredVisibleSpots.length}</strong>
        </div>
        <div className="stat-pill">
          <span>Cheapest</span>
          <strong>
            {cheapestVisible ? numberFormat.format(cheapestVisible.price) : "None"}
          </strong>
        </div>
        <div className="stat-pill">
          <span>Cities</span>
          <strong>{visibleCities}</strong>
        </div>
        <div className="stat-pill">
          <span>Average</span>
          <strong>{numberFormat.format(averageVisiblePrice || 0)}</strong>
        </div>
      </div>

      <div className="map-hint">
        <span className="overlay-label">Viewport ranking</span>
        <strong>{mapReady ? "Live on move" : "Loading map"}</strong>
      </div>

      {!mapboxAccessToken || mapError ? (
        <div className="map-fallback">
          <span className="overlay-label">Map</span>
          <strong>{mapError || "Unavailable"}</strong>
          <p>Add `VITE_MAPBOX_ACCESS_TOKEN` in `.env` to enable the live map.</p>
        </div>
      ) : null}

      <aside className={`floating-sidebar ${sidebarOpen ? "" : "is-hidden"}`.trim()}>
        <div className="sidebar-top">
          <div>
            <p className="sidebar-kicker">In current view</p>
            <h2>Cheapest first</h2>
          </div>
          <div className="sidebar-count">{filteredVisibleSpots.length}</div>
        </div>

        {selectedVisibleSpot ? (
          <section className="selected-card">
            <div className="selected-head">
              <div>
                <p className="sidebar-kicker">Selected venue</p>
                <h3>{selectedVisibleSpot.name}</h3>
              </div>
              <strong>{numberFormat.format(selectedVisibleSpot.price)}</strong>
            </div>
            <p>
              {selectedVisibleSpot.city}, {selectedVisibleSpot.canton} ·{" "}
              {selectedVisibleSpot.beer}
            </p>
            <p>{selectedVisibleSpot.address}</p>
            <small>{selectedVisibleSpot.vibe}</small>
          </section>
        ) : null}

        <div className="sidebar-scroll">
          {loading ? (
            <div className="empty-card">Loading venues…</div>
          ) : visibleSpots.length === 0 ? (
            <div className="empty-card">
              Move the map to bring bars and restaurants into view.
            </div>
          ) : filteredVisibleSpots.length === 0 ? (
            <div className="empty-card">
              No visible venues match your current search.
            </div>
          ) : (
            <div className="results-list">
              {filteredVisibleSpots
                .filter((spot) => spot.id !== selectedVisibleSpot?.id)
                .map((spot, index) => (
                  <button
                    key={spot.id}
                    type="button"
                    className="result-card"
                    onClick={() => focusSpot(spot)}
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
        </div>
      </aside>
    </div>
  );
}

export default App;
