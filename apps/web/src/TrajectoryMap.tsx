import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import { GeoJSONSource, LngLatBounds } from "maplibre-gl";
import type { FeatureCollection, LineString, Point } from "geojson";
import { Crosshair, Layers, Minus, Plus } from "lucide-react";
import type { ContourGeometry, Sample } from "./types";
import "maplibre-gl/dist/maplibre-gl.css";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";

// MapLibre 6 ships a separate module worker. Vite must emit it as a local asset.
maplibregl.setWorkerUrl(workerUrl);
maplibregl.setWorkerCount(2);

const grid: FeatureCollection<LineString> = {
  type: "FeatureCollection",
  features: [],
};
for (let x = -180; x <= 180; x += 5)
  grid.features.push({
    type: "Feature",
    properties: {},
    geometry: {
      type: "LineString",
      coordinates: [
        [x, -85],
        [x, 85],
      ],
    },
  });
for (let y = -80; y <= 80; y += 5)
  grid.features.push({
    type: "Feature",
    properties: {},
    geometry: {
      type: "LineString",
      coordinates: [
        [-180, y],
        [180, y],
      ],
    },
  });

type MapPoint = Pick<Sample, "latitude_deg" | "longitude_deg">;

function coordinates(samples: MapPoint[], anchor?: number) {
  const coords: number[][] = [];
  for (const p of samples) {
    let lon = p.longitude_deg;
    const previous = coords.length ? coords[coords.length - 1][0] : anchor;
    if (previous !== undefined) lon += 360 * Math.round((previous - lon) / 360);
    coords.push([lon, p.latitude_deg]);
  }
  return coords;
}

export function TrajectoryMap({
  samples,
  secondarySamples,
  index,
  synthetic,
  onSelect,
  windVectors,
  windTips,
  contours,
  contourRange,
  probePoint,
  weatherBounds,
  onLocationSelect,
}: {
  samples: MapPoint[];
  secondarySamples?: MapPoint[];
  index: number;
  synthetic: boolean;
  onSelect: (i: number) => void;
  windVectors?: FeatureCollection<ContourGeometry>;
  windTips?: FeatureCollection<Point>;
  contours?: FeatureCollection<ContourGeometry>;
  contourRange?: [number, number];
  probePoint?: [number, number];
  weatherBounds?: [number, number, number, number];
  onLocationSelect?: (lat: number, lon: number) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const samplesRef = useRef(samples);
  const selectRef = useRef(onSelect);
  const locationRef = useRef(onLocationSelect);
  const fittedBounds = useRef("");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [borders, setBorders] = useState(true);
  useEffect(() => {
    samplesRef.current = samples;
    selectRef.current = onSelect;
    locationRef.current = onLocationSelect;
  }, [samples, onSelect, onLocationSelect]);

  useEffect(() => {
    if (!container.current) return;
    let map: maplibregl.Map;
    try {
      map = new maplibregl.Map({
        container: container.current,
        center: [12, 46],
        zoom: 4.3,
        attributionControl: false,
        maxZoom: 12,
        minZoom: 1.3,
        style: {
          version: 8,
          sources: {
            countries: { type: "geojson", data: "/countries.geojson" },
            grid: { type: "geojson", data: grid },
          },
          layers: [
            {
              id: "water",
              type: "background",
              paint: { "background-color": "#11171c" },
            },
            {
              id: "land",
              type: "fill",
              source: "countries",
              paint: {
                "fill-color": "#22282b",
              },
            },
            {
              id: "graticule",
              type: "line",
              source: "grid",
              paint: {
                "line-color": "#9eafb5",
                "line-opacity": 0.11,
                "line-width": 0.7,
              },
            },
            {
              id: "borders",
              type: "line",
              source: "countries",
              paint: {
                "line-color": "#606c70",
                "line-width": 0.7,
                "line-opacity": 0.55,
              },
            },
          ],
        },
      });
    } catch (e) {
      queueMicrotask(() =>
        setError(
          `Map unavailable: ${String(e)}. Use the accessible sample inspector and CSV export.`,
        ),
      );
      return;
    }
    mapRef.current = map;
    const labelDensity = () =>
      map
        .getContainer()
        .classList.toggle("show-city-labels", map.getZoom() >= 5);
    map.on("zoom", labelDensity);
    labelDensity();
    map.addControl(
      new maplibregl.ScaleControl({ maxWidth: 100, unit: "metric" }),
      "bottom-left",
    );
    map.addControl(
      new maplibregl.AttributionControl({
        compact: false,
        customAttribution:
          "Natural Earth · public domain · coarse geography, no terrain",
      }),
      "bottom-right",
    );
    map.on("load", () => {
      map.addSource("weather-bounds", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "weather-bounds-fill",
        type: "fill",
        source: "weather-bounds",
        paint: { "fill-color": "#8ac5d1", "fill-opacity": 0.035 },
      });
      map.addLayer({
        id: "weather-bounds-line",
        type: "line",
        source: "weather-bounds",
        paint: {
          "line-color": "#8ac5d1",
          "line-width": 1,
          "line-opacity": 0.55,
          "line-dasharray": [3, 4],
        },
      });
      map.addSource("weather-contours", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "weather-contours",
        type: "line",
        source: "weather-contours",
        paint: {
          "line-width": 1.4,
          "line-color": "#8ac5d1",
          "line-opacity": 0.7,
        },
      });
      map.addSource("wind-field", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "wind-field",
        type: "line",
        source: "wind-field",
        paint: {
          "line-width": 1.5,
          "line-color": "#8ac5d1",
          "line-opacity": 0.8,
        },
      });
      map.addSource("wind-tips", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "wind-tips",
        type: "circle",
        source: "wind-tips",
        paint: { "circle-radius": 2.5, "circle-color": "#bfe5ea" },
      });
      map.on("click", (e) =>
        locationRef.current?.(
          e.lngLat.lat,
          ((((e.lngLat.lng + 180) % 360) + 360) % 360) - 180,
        ),
      );
      map.addSource("route", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "route-halo",
        type: "line",
        source: "route",
        paint: {
          "line-color": "#6cb7c6",
          "line-width": 7,
          "line-opacity": 0.08,
        },
      });
      map.addLayer({
        id: "route",
        type: "line",
        source: "route",
        paint: {
          "line-color": "#8bd0d9",
          "line-width": 2.2,
          "line-dasharray": [3, 2],
        },
      });
      map.addSource("route-secondary", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "route-secondary",
        type: "line",
        source: "route-secondary",
        paint: {
          "line-color": "#deb77a",
          "line-width": 2.2,
          "line-dasharray": [1, 2],
        },
      });
      map.addSource("secondary-selected", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "secondary-selection",
        type: "circle",
        source: "secondary-selected",
        paint: {
          "circle-radius": 6,
          "circle-color": "#deb77a",
          "circle-stroke-color": "#473b26",
          "circle-stroke-width": 3,
        },
      });
      map.addSource("samples", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "sample-points",
        type: "circle",
        source: "samples",
        paint: {
          "circle-radius": 2.5,
          "circle-color": "#9dd5de",
          "circle-opacity": 0.15,
        },
      });
      map.addSource("selected", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: "selection-halo",
        type: "circle",
        source: "selected",
        paint: {
          "circle-radius": 18,
          "circle-color": "#6cb7c6",
          "circle-opacity": 0.13,
        },
      });
      map.addLayer({
        id: "selection",
        type: "circle",
        source: "selected",
        paint: {
          "circle-radius": 6,
          "circle-color": "#e4f4f5",
          "circle-stroke-color": "#6cb7c6",
          "circle-stroke-width": 3,
        },
      });
      // Country labels are local HTML: no remote glyph server or font requests.
      const labels = [
        ["ITALY", 12.8, 42.8],
        ["FRANCE", 2.3, 46.6],
        ["SWITZERLAND", 8.2, 46.8],
        ["AUSTRIA", 14, 47.8],
        ["GERMANY", 10.6, 50.7],
        ["CROATIA", 16.9, 45.4],
        ["SLOVENIA", 14.9, 46.1],
        ["HUNGARY", 19.5, 47.2],
        ["BOSNIA", 17.9, 44],
        ["POLAND", 19, 52.2],
        ["SPAIN", -3, 40.5],
      ] as const;
      labels.forEach(([name, lon, lat]) => {
        const el = document.createElement("span");
        el.className = "country-label";
        el.textContent = name;
        new maplibregl.Marker({ element: el }).setLngLat([lon, lat]).addTo(map);
      });
      const cities = [
        ["Milan", 9.19, 45.46],
        ["Piacenza", 9.69, 45.05],
        ["Verona", 10.99, 45.44],
        ["Venice", 12.32, 45.44],
        ["Trieste", 13.77, 45.65],
        ["Zagreb", 15.98, 45.81],
        ["Ljubljana", 14.51, 46.06],
        ["Ravenna", 12.2, 44.42],
      ] as const;
      cities.forEach(([name, lon, lat]) => {
        const el = document.createElement("span");
        el.className = "city-label";
        el.textContent = name;
        new maplibregl.Marker({ element: el, anchor: "left", offset: [5, 0] })
          .setLngLat([lon, lat])
          .addTo(map);
      });
      map.on("click", "sample-points", (e) => {
        const i = e.features?.[0]?.properties?.index;
        if (typeof i === "number") selectRef.current(i);
      });
      map.on("mouseenter", "sample-points", () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", "sample-points", () => {
        map.getCanvas().style.cursor = "";
      });
      setLoaded(true);
    });
    map.on("error", (e) => {
      setError(`Map data error: ${e.error.message}`);
    });
    const resize = new ResizeObserver(() => map.resize());
    resize.observe(container.current);
    return () => {
      resize.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded) return;
    const coords = coordinates(samples);
    (map.getSource("route") as GeoJSONSource).setData(
      coords.length >= 2
        ? {
            type: "Feature",
            properties: {},
            geometry: { type: "LineString", coordinates: coords },
          }
        : { type: "FeatureCollection", features: [] },
    );
    const secondary = coordinates(secondarySamples ?? [], coords[0]?.[0]);
    (map.getSource("route-secondary") as GeoJSONSource).setData(
      secondary.length >= 2
        ? {
            type: "Feature",
            properties: {},
            geometry: { type: "LineString", coordinates: secondary },
          }
        : { type: "FeatureCollection", features: [] },
    );
    const points: FeatureCollection<Point> = {
      type: "FeatureCollection",
      features: coords.map((c, i) => ({
        type: "Feature",
        properties: { index: i },
        geometry: { type: "Point", coordinates: c },
      })),
    };
    (map.getSource("samples") as GeoJSONSource).setData(points);
    if (coords.length > 1) {
      const bounds = new LngLatBounds();
      [...coords, ...secondary].forEach((c) => bounds.extend([c[0], c[1]]));
      map.fitBounds(bounds, {
        padding: { top: 100, right: 90, bottom: 90, left: 90 },
        maxZoom: 6.6,
        duration: 0,
      });
    }
    if (coords.length) {
      const el = document.createElement("span");
      el.className = "launch-label";
      el.textContent = secondarySamples ? "WINDOW START" : "START";
      const marker = new maplibregl.Marker({
        element: el,
        anchor: "top-left",
        offset: [8, 8],
      })
        .setLngLat([coords[0][0], coords[0][1]])
        .addTo(map);
      return () => {
        marker.remove();
      };
    }
  }, [samples, secondarySamples, loaded]);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded || !samples[index]) return;
    const coord = coordinates(samples)[index];
    (map.getSource("selected") as GeoJSONSource).setData({
      type: "Feature",
      properties: {},
      geometry: { type: "Point", coordinates: coord },
    });
    const secondary = coordinates(
      secondarySamples ?? [],
      coordinates(samples)[0]?.[0],
    )[index];
    (map.getSource("secondary-selected") as GeoJSONSource).setData(
      secondary
        ? {
            type: "Feature",
            properties: {},
            geometry: { type: "Point", coordinates: secondary },
          }
        : { type: "FeatureCollection", features: [] },
    );
  }, [index, samples, secondarySamples, loaded]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loaded || !windVectors) return;
    (map.getSource("wind-field") as GeoJSONSource).setData(windVectors);
    if (windTips)
      (map.getSource("wind-tips") as GeoJSONSource).setData(windTips);
  }, [loaded, windVectors, windTips]);
  useEffect(() => {
    if (!loaded || !mapRef.current || !contours) return;
    const map = mapRef.current;
    (map.getSource("weather-contours") as GeoJSONSource).setData(contours);
    if (contourRange && contourRange[1] > contourRange[0]) {
      const [low, high] = contourRange;
      map.setPaintProperty("weather-contours", "line-color", [
        "interpolate",
        ["linear"],
        ["get", "value"],
        low,
        "#6f95c4",
        (low + high) / 2,
        "#8ac5d1",
        high,
        "#deb77a",
      ]);
    }
  }, [loaded, contours, contourRange]);
  useEffect(() => {
    if (!loaded || !mapRef.current || !probePoint) return;
    (mapRef.current.getSource("selected") as GeoJSONSource).setData({
      type: "Feature",
      properties: {},
      geometry: { type: "Point", coordinates: probePoint },
    });
  }, [loaded, probePoint]);
  useEffect(() => {
    if (loaded && weatherBounds && mapRef.current) {
      const key = weatherBounds.join(",");
      if (fittedBounds.current === key) return;
      fittedBounds.current = key;
      const [w, s, e, n] = weatherBounds;
      (mapRef.current.getSource("weather-bounds") as GeoJSONSource).setData({
        type: "Feature",
        properties: {},
        geometry: {
          type: "Polygon",
          coordinates: [
            [
              [w, s],
              [e, s],
              [e, n],
              [w, n],
              [w, s],
            ],
          ],
        },
      });
      mapRef.current?.fitBounds(
        [
          [weatherBounds[0], weatherBounds[1]],
          [weatherBounds[2], weatherBounds[3]],
        ],
        { padding: 40, duration: 0 },
      );
    }
  }, [loaded, weatherBounds]);

  function fit() {
    const coords = coordinates(samples);
    if (coords.length < 2) {
      if (weatherBounds)
        mapRef.current?.fitBounds(
          [
            [weatherBounds[0], weatherBounds[1]],
            [weatherBounds[2], weatherBounds[3]],
          ],
          { padding: 40, duration: 300 },
        );
      return;
    }
    const bounds = new LngLatBounds();
    [...coords, ...coordinates(secondarySamples ?? [], coords[0]?.[0])].forEach(
      (c) => bounds.extend([c[0], c[1]]),
    );
    mapRef.current?.fitBounds(bounds, {
      padding: 90,
      maxZoom: 6.6,
      duration: 300,
    });
  }
  return (
    <div
      className="map-wrap"
      data-map-ready={loaded}
      data-sample-count={samples.length}
      data-secondary-sample-count={secondarySamples?.length ?? 0}
    >
      <div
        ref={container}
        className="map-canvas"
        role="region"
        aria-label={
          windVectors
            ? "Interactive forecast field map"
            : "Interactive predicted trajectory map"
        }
      />
      <div className="map-label">
        <span className="tiny-dot cyan" /> WGS84{" "}
        <span className="divider">/</span>{" "}
        {windVectors
          ? "FORECAST WIND FIELD"
          : secondarySamples
            ? "ALIGNED SCENARIOS"
            : "2D TRAJECTORY"}
      </div>
      <div className="map-tools">
        <button
          title="Fit predicted track"
          aria-label="Fit predicted track"
          onClick={fit}
        >
          <Crosshair size={17} />
        </button>
        <button
          title="Zoom in"
          aria-label="Zoom in"
          onClick={() => mapRef.current?.zoomIn()}
        >
          <Plus size={17} />
        </button>
        <button
          title="Zoom out"
          aria-label="Zoom out"
          onClick={() => mapRef.current?.zoomOut()}
        >
          <Minus size={17} />
        </button>
        <button
          title="Toggle country boundaries"
          aria-label="Toggle country boundaries"
          aria-pressed={borders}
          onClick={() => {
            setBorders(!borders);
            mapRef.current?.setLayoutProperty(
              "borders",
              "visibility",
              borders ? "none" : "visible",
            );
          }}
        >
          <Layers size={17} />
        </button>
      </div>
      {synthetic && (
        <div className="demo-watermark">
          DEMO DATA <span>Analytic constant-wind field</span>
        </div>
      )}
      <div className="map-legend">
        <i />{" "}
        {windVectors
          ? "10-minute wind displacement"
          : secondarySamples
            ? "Reference prediction"
            : "Predicted L0 path"}{" "}
        <span className="legend-dot" />{" "}
        {windVectors
          ? "Wind direction endpoint"
          : secondarySamples
            ? "Selected reference"
            : "Selected sample"}
        {secondarySamples && (
          <>
            <span className="legend-candidate" />
            Candidate prediction
          </>
        )}
      </div>
      {error && (
        <div className="map-error" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}
