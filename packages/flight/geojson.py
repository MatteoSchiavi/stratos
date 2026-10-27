"""RFC7946 2D trajectory export; split the antimeridian instead of drawing across the world."""


def geometry(samples: list[dict]) -> dict:
    lines: list[list[list[float]]] = [[]]
    for sample in samples:
        point = [sample["longitude_deg"], sample["latitude_deg"]]
        if lines[-1]:
            previous = lines[-1][-1]
            difference = point[0] - previous[0]
            if abs(difference) > 180:
                adjusted = point[0] - 360 if difference > 180 else point[0] + 360
                boundary = -180 if difference > 180 else 180
                fraction = (boundary - previous[0]) / (adjusted - previous[0])
                latitude = previous[1] + fraction * (point[1] - previous[1])
                lines[-1].append([boundary, latitude])
                lines.append([[-boundary, latitude]])
        lines[-1].append(point)
    if len(lines) == 1:
        return {"type": "LineString", "coordinates": lines[0]}
    return {"type": "MultiLineString", "coordinates": lines}
