import { lazy, Suspense } from "react";
import type { ComponentProps } from "react";
import type { TrajectoryMap as MapImplementation } from "./TrajectoryMap";

const Map = lazy(() =>
  import("./TrajectoryMap").then((module) => ({
    default: module.TrajectoryMap,
  })),
);

export function TrajectoryMap(props: ComponentProps<typeof MapImplementation>) {
  return (
    <Suspense
      fallback={
        <div className="map-wrap map-loading" role="status">
          Loading local map renderer…
        </div>
      }
    >
      <Map {...props} />
    </Suspense>
  );
}
