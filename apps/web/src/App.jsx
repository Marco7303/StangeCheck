import {
  useDeferredValue,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import mapboxgl from "mapbox-gl";
import logoLight from "./assets/logo-light.svg";
import { flagVenuePrice, listVenues } from "./lib/venues";

const minimumLoaderMs = 2000;
const adBanners = Object.entries(
  import.meta.glob("./assets/ad-banners/*.{png,jpg,jpeg,webp}", {
    eager: true,
    import: "default",
  }),
)
  .sort(([leftPath], [rightPath]) => leftPath.localeCompare(rightPath))
  .map(([path, src]) => ({
    src,
    alt: path
      .split("/")
      .pop()
      ?.replace(/\.[^.]+$/, "")
      .replace(/[-_]+/g, " ") ?? "Advertisement",
  }));
const popupAds = Object.entries(
  import.meta.glob("./assets/ad-popup/*.{png,jpg,jpeg,webp}", {
    eager: true,
    import: "default",
  }),
)
  .sort(([leftPath], [rightPath]) => leftPath.localeCompare(rightPath))
  .map(([path, src]) => ({
    key:
      path
        .split("/")
        .pop()
        ?.replace(/\.[^.]+$/, "") ?? "sponsored-event",
    src,
    alt: path
      .split("/")
      .pop()
      ?.replace(/\.[^.]+$/, "")
      .replace(/[-_]+/g, " ") ?? "Sponsored event",
  }));

const popupAdContent = {
  jazz: {
    title: "Zug Jazz Night",
    body: "Live set in Zug. Save before it sells out.",
  },
  schwimm: {
    title: "Schwimmfest Zug",
    body: "Summer swims, music, and a quick ticket deal.",
  },
  tech: {
    title: "Tech am See",
    body: "Late-night techno by the lake. Loud, fast, and local.",
  },
};

function getRandomAdIndex() {
  if (!adBanners.length) {
    return 0;
  }

  return Math.floor(Math.random() * adBanners.length);
}

function getNextAdIndex(currentIndex) {
  if (adBanners.length <= 1) {
    return currentIndex;
  }

  return (currentIndex + 1) % adBanners.length;
}

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

function compareByPrice(left, right) {
  if (left.price == null && right.price == null) {
    return left.name.localeCompare(right.name);
  }

  if (left.price == null) {
    return 1;
  }

  if (right.price == null) {
    return -1;
  }

  if (left.price === right.price) {
    return left.name.localeCompare(right.name);
  }

  return left.price - right.price;
}

function formatPrice(value) {
  return value == null ? "Price pending" : numberFormat.format(value);
}

function formatMarkerPrice(value) {
  return value == null ? "Pending" : numberFormat.format(value);
}

function getMapBounds(spots) {
  if (!spots.length) {
    return swissBounds;
  }

  const latitudes = spots.map((spot) => spot.lat);
  const longitudes = spots.map((spot) => spot.lng);
  const minLat = Math.min(...latitudes);
  const maxLat = Math.max(...latitudes);
  const minLng = Math.min(...longitudes);
  const maxLng = Math.max(...longitudes);
  const latPadding = Math.max((maxLat - minLat) * 0.2, 0.01);
  const lngPadding = Math.max((maxLng - minLng) * 0.2, 0.01);

  return [
    [minLng - lngPadding, minLat - latPadding],
    [maxLng + lngPadding, maxLat + latPadding],
  ];
}

function buildDirectionsUrl(spot) {
  const destination = [
    spot.name,
    spot.address,
    spot.city,
    spot.canton,
    "Switzerland",
  ].join(", ");

  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(destination)}`;
}

function App() {
  const [spots, setSpots] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [loading, setLoading] = useState(true);
  const [showLoader, setShowLoader] = useState(true);
  const [loaderExiting, setLoaderExiting] = useState(false);
  const [loadingProgress, setLoadingProgress] = useState(10);
  const [activeAdIndex, setActiveAdIndex] = useState(() => getRandomAdIndex());
  const [popupVisible, setPopupVisible] = useState(false);
  const [popupDismissed, setPopupDismissed] = useState(false);
  const [popupAdIndex] = useState(() =>
    popupAds.length ? Math.floor(Math.random() * popupAds.length) : 0,
  );
  const [flaggingVenueId, setFlaggingVenueId] = useState(null);
  const [flagError, setFlagError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [visibleIds, setVisibleIds] = useState([]);
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState("");
  const [searchValue, setSearchValue] = useState("");
  const deferredSearch = useDeferredValue(searchValue);
  const popupStatusId = useId();
  const loadStartedAtRef = useRef(Date.now());
  const mapRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const markersRef = useRef(new Map());
  const popupRef = useRef(null);
  const visibleIdsRef = useRef([]);

  useEffect(() => {
    let active = true;
    loadStartedAtRef.current = Date.now();

    setLoading(true);
    setLoadError("");

    listVenues()
      .then((rows) => {
        if (!active) {
          return;
        }

        setSpots(
          rows.filter(
            (row) => Number.isFinite(row.lat) && Number.isFinite(row.lng),
          ),
        );
        setSelectedId(null);
      })
      .catch((error) => {
        if (!active) {
          return;
        }

        setSpots([]);
        setLoadError(
          error instanceof Error ? error.message : "Unable to load venues.",
        );
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!loading) {
      const elapsed = Date.now() - loadStartedAtRef.current;
      const remaining = Math.max(minimumLoaderMs - elapsed, 0);
      const timeoutId = window.setTimeout(() => {
        setLoadingProgress(100);
        setLoaderExiting(true);
      }, remaining);

      const hideTimeoutId = window.setTimeout(() => {
        setShowLoader(false);
      }, remaining + 900);

      return () => {
        window.clearTimeout(timeoutId);
        window.clearTimeout(hideTimeoutId);
      };
    }

    setShowLoader(true);
    setLoaderExiting(false);
    setLoadingProgress(8);

    const progressInterval = window.setInterval(() => {
      const elapsed = Date.now() - loadStartedAtRef.current;
      const progressRatio = Math.min(elapsed / minimumLoaderMs, 1);
      const nextProgress = 8 + progressRatio * 76;
      setLoadingProgress(Math.min(nextProgress, 84));
    }, 60);

    return () => {
      window.clearInterval(progressInterval);
    };
  }, [loading]);

  const visibleSpots = useMemo(() => {
    return spots
      .filter((spot) => visibleIds.includes(spot.id))
      .sort(compareByPrice);
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
  const datasetBounds = useMemo(() => getMapBounds(spots), [spots]);
  const activeAd = adBanners[activeAdIndex] ?? null;
  const activePopupAd = popupAds[popupAdIndex] ?? null;
  const activePopupContent =
    popupAdContent[activePopupAd?.key] ?? popupAdContent.jazz;

  const pricedVisibleSpots = filteredVisibleSpots.filter(
    (spot) => spot.price != null,
  );
  const cheapestVisible = pricedVisibleSpots[0] ?? null;
  const averageVisiblePrice =
    pricedVisibleSpots.reduce((total, spot) => total + spot.price, 0) /
      (pricedVisibleSpots.length || 1);
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

    mapInstanceRef.current.fitBounds(datasetBounds, {
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

  async function handleFlagVenuePrice(venueId) {
    if (!venueId || flaggingVenueId === venueId) {
      return;
    }

    setFlaggingVenueId(venueId);
    setFlagError("");

    try {
      await flagVenuePrice(venueId);
      setSpots((currentSpots) =>
        currentSpots.map((spot) =>
          spot.id === venueId ? { ...spot, userFlagged: true } : spot,
        ),
      );
    } catch (error) {
      setFlagError(
        error instanceof Error ? error.message : "Unable to flag this price.",
      );
    } finally {
      setFlaggingVenueId(null);
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
        bounds: datasetBounds,
        fitBoundsOptions: {
          padding: {
            top: 110,
            right: 430,
            bottom: 42,
            left: 32,
          },
        },
        attributionControl: false,
        pitch: 0,
        bearing: 0,
        config: {
          basemap: {
            lightPreset: "day",
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
      const handleMapSurfaceClick = (event) => {
        const target = event.target;

        if (
          target instanceof Element &&
          target.closest(".custom-marker, .mapboxgl-popup")
        ) {
          return;
        }

        setSelectedId(null);
      };

      spots.forEach((spot) => {
        const markerNode = document.createElement("button");
        markerNode.type = "button";
        markerNode.className = "custom-marker";
        markerNode.setAttribute(
          "aria-label",
          `${spot.name} in ${spot.city} for ${formatPrice(spot.price)}`,
        );
        markerNode.innerHTML = `<strong>${formatMarkerPrice(spot.price)}</strong>`;

        const marker = new mapboxgl.Marker({
          element: markerNode,
          anchor: "bottom",
        })
          .setLngLat([spot.lng, spot.lat])
          .addTo(map);

        markerNode.addEventListener("click", (event) => {
          event.stopPropagation();
          setSelectedId(spot.id);
          setSidebarOpen(true);
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
      map.getCanvasContainer().addEventListener("click", handleMapSurfaceClick);
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
        map
          .getCanvasContainer()
          .removeEventListener("click", handleMapSurfaceClick);
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
  }, [spots, datasetBounds]);

  useEffect(() => {
    markersRef.current.forEach(({ marker, node }, markerId) => {
      node.classList.toggle("is-selected", markerId === selectedVisibleSpot?.id);
      node.classList.toggle("is-visible", visibleIds.includes(markerId));
      node.classList.toggle("is-cheapest", markerId === cheapestVisible?.id);
      marker.getElement().style.zIndex =
        markerId === selectedVisibleSpot?.id ? "14" : markerId === cheapestVisible?.id ? "12" : "10";
    });
  }, [selectedVisibleSpot, visibleIds, cheapestVisible]);

  useEffect(() => {
    if (!selectedVisibleSpot || !mapInstanceRef.current || !popupRef.current) {
      popupRef.current?.remove();
      return;
    }

    const directionsUrl = buildDirectionsUrl(selectedVisibleSpot);
    const isFlagged = selectedVisibleSpot.userFlagged === true;
    const isFlagging = flaggingVenueId === selectedVisibleSpot.id;
    const statusMessage = flagError
      ? flagError
      : isFlagged
        ? "This price has been flagged."
        : "";
    const statusClassName = flagError
      ? "info-window-status is-error"
      : "info-window-status";

    popupRef.current.setHTML(`
      <div class="info-window">
        <div class="info-window-head">
          <div>
            <p class="info-window-kicker">${selectedVisibleSpot.city}, ${selectedVisibleSpot.canton}</p>
            <strong>${selectedVisibleSpot.name}</strong>
          </div>
        </div>
        <p class="info-window-meta">${selectedVisibleSpot.beer}</p>
        <p class="info-window-address">${selectedVisibleSpot.address}</p>
        <a class="info-window-link" href="${directionsUrl}" target="_blank" rel="noreferrer">
          Open in Google Maps
        </a>
        ${isFlagged ? "" : `
        <button
          type="button"
          class="info-window-secondary"
          data-flag-price-button="true"
          ${isFlagging ? "disabled" : ""}
          aria-describedby="${popupStatusId}"
        >
          ${isFlagging ? "Flagging..." : "Flag wrong/outdated price"}
        </button>
        `}
        <p id="${popupStatusId}" class="${statusClassName}">
          ${statusMessage}
        </p>
      </div>
    `);

    popupRef.current
      .setLngLat([selectedVisibleSpot.lng, selectedVisibleSpot.lat])
      .addTo(mapInstanceRef.current);

    const popupNode = popupRef.current.getElement();
    const flagButton = popupNode?.querySelector("[data-flag-price-button='true']");

    if (!flagButton) {
      return;
    }

    const handleFlagButtonClick = (event) => {
      event.preventDefault();
      handleFlagVenuePrice(selectedVisibleSpot.id);
    };

    flagButton.addEventListener("click", handleFlagButtonClick);

    return () => {
      flagButton.removeEventListener("click", handleFlagButtonClick);
    };
  }, [flagError, flaggingVenueId, popupStatusId, selectedVisibleSpot]);

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

  useEffect(() => {
    if (popupDismissed) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setPopupVisible(true);
    }, 10000);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [popupDismissed]);

  function handleClosePopup() {
    setPopupVisible(false);
    setPopupDismissed(true);
  }

  useEffect(() => {
    setFlagError("");
  }, [selectedId]);

  return (
    <div className="screen">
      {showLoader ? (
        <div
          className={`loading-screen ${loaderExiting ? "is-complete" : ""}`.trim()}
        >
          <div className="loading-panel">
            <img
              className="loading-logo"
              src={logoLight}
              alt="Stange Check"
            />
            <div className="loading-track" aria-hidden="true">
              <div
                className="loading-bar"
                style={{ width: `${loadingProgress}%` }}
              />
            </div>
            <span className="loading-percent">
              {Math.round(loadingProgress)}%
            </span>
          </div>
        </div>
      ) : null}

      <div ref={mapRef} className="map-canvas" />
      <div className="map-scrim" />

      {popupVisible && activePopupAd ? (
        <aside
          className="event-popup"
          aria-label="Sponsored event advertisement"
        >
          <button
            type="button"
            className="event-popup-close"
            aria-label="Close advertisement"
            onClick={handleClosePopup}
          >
            X
          </button>
          <div className="event-popup-copy">
            <span className="event-popup-tag">Sponsored</span>
            <h3>{activePopupContent.title}</h3>
            <p>{activePopupContent.body}</p>
          </div>
          <div className="event-popup-media">
            <img src={activePopupAd.src} alt={activePopupAd.alt} />
          </div>
        </aside>
      ) : null}

      <header className="floating-topbar">
        <div className="brand">
          <img
            className="brand-logo"
            src={logoLight}
            alt="Stange Check"
          />
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
            placeholder="Search visible venues or beer names"
          />
        </form>

        <div className="topbar-actions">
          <button type="button" className="control-button" onClick={resetMapView}>
            Reset
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
          <strong>
            {pricedVisibleSpots.length
              ? numberFormat.format(averageVisiblePrice || 0)
              : "None"}
          </strong>
        </div>
      </div>

      {!mapboxAccessToken || mapError ? (
        <div className="map-fallback">
          <span className="overlay-label">Map</span>
          <strong>{mapError || "Unavailable"}</strong>
          <p>Add `VITE_MAPBOX_ACCESS_TOKEN` in `.env` to enable the live map.</p>
        </div>
      ) : null}

      <div className="sidebar-dock">
        <aside
          className={`floating-sidebar ${sidebarOpen ? "" : "is-hidden"}`.trim()}
        >
          <div className="sidebar-top">
            <div>
              <h2>{filteredVisibleSpots.length} Prices found</h2>
            </div>
            <button
              type="button"
              className="sidebar-close"
              aria-label="Close prices sidebar"
              onClick={() => setSidebarOpen(false)}
            >
              X
            </button>
          </div>

          <div className="sidebar-scroll">
            {loading ? (
              <div className="empty-card">Loading venues…</div>
            ) : loadError ? (
              <div className="empty-card">
                <strong>Venue data unavailable.</strong>
                <p>{loadError}</p>
              </div>
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
                {filteredVisibleSpots.map((spot) => (
                  <button
                    key={spot.id}
                    type="button"
                    className={`result-card ${spot.id === cheapestVisible?.id ? "is-cheapest" : ""}`.trim()}
                    onClick={() => focusSpot(spot)}
                  >
                    <div className="result-main">
                      <div className="result-topline">
                        <h4>{spot.name}</h4>
                        <strong>{formatPrice(spot.price)}</strong>
                      </div>
                      <p>
                        {spot.city}, {spot.canton} · {spot.beer}
                      </p>
                      {spot.address ? <small><em>{spot.address}</em></small> : null}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          {activeAd ? (
            <button
              type="button"
              className="sidebar-ad"
              onClick={() => setActiveAdIndex((current) => getNextAdIndex(current))}
            >
              <img src={activeAd.src} alt={activeAd.alt} />
            </button>
          ) : null}
        </aside>

        {!sidebarOpen ? (
          <button
            type="button"
            className="sidebar-tab"
            aria-label="Show prices sidebar"
            onClick={() => setSidebarOpen(true)}
          >
            <span className="sidebar-tab-label">Prices</span>
          </button>
        ) : null}
      </div>
    </div>
  );
}

export default App;
