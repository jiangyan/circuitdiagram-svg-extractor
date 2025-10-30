"""
Base extractor class with shared utilities for all extractors.
"""
import math
from typing import List, Tuple
from models import Connection, TextElement, WireSpec


class BaseExtractor:
    """Base class for all connection extractors with shared utility methods."""

    def __init__(self, text_elements: List[TextElement], wire_specs: List[WireSpec]):
        """
        Initialize base extractor with common data.

        Args:
            text_elements: List of all text elements from the SVG
            wire_specs: List of wire specifications (diameter, color)
        """
        self.text_elements = text_elements
        self.wire_specs = wire_specs

    def _find_wire_spec_for_rectangular_polyline(self, path_points: List[Tuple[float, float]]) -> Tuple[str, str]:
        """
        Find the wire spec for a rectangular polyline by prioritizing the LONGEST horizontal segment.

        Rectangular polylines typically have a short horizontal segment at the entry point
        and a long horizontal segment that carries the main wire with its spec.

        Args:
            path_points: List of (x, y) coordinates along the rectangular polyline

        Returns:
            Tuple of (diameter, color) or (None, None) if no spec found
        """
        if not self.wire_specs or len(path_points) < 2:
            return (None, None)

        # Find all horizontal segments and their lengths
        horizontal_segments = []
        for i in range(len(path_points) - 1):
            x1, y1 = path_points[i]
            x2, y2 = path_points[i + 1]

            # Check if this segment is horizontal (Y change < 5 units)
            if abs(y2 - y1) < 5:
                length = abs(x2 - x1)
                horizontal_segments.append((length, x1, y1, x2, y2))

        if not horizontal_segments:
            return (None, None)

        # Sort by length (longest first)
        horizontal_segments.sort(reverse=True)

        # Use the longest horizontal segment to find wire spec
        _, x1, y1, x2, y2 = horizontal_segments[0]
        min_x, max_x = min(x1, x2), max(x1, x2)
        segment_y = (y1 + y2) / 2

        # Find wire spec on this segment
        closest_spec = None
        min_dist = float('inf')

        for spec in self.wire_specs:
            # Spec must be on the horizontal segment (within ±15 Y units)
            if abs(spec.y - segment_y) < 15:
                # Spec should be between the X endpoints of the segment
                if min_x - 50 < spec.x < max_x + 50:
                    dist = abs(spec.y - segment_y)
                    if dist < min_dist:
                        min_dist = dist
                        closest_spec = spec

        if closest_spec:
            return (closest_spec.diameter, closest_spec.color)
        return (None, None)

    def _find_wire_spec_near_path(self, path_points: List[Tuple[float, float]], source_point: Tuple[float, float] = None) -> Tuple[str, str]:
        """
        Find the wire spec closest to a routing path.

        CRITICAL: Wire specs are positioned above the INITIAL horizontal segment of the wire,
        near where the wire originates (source). NOT scattered along the entire path!

        For L-shaped or complex paths, we find the horizontal segment closest to the SOURCE endpoint.

        Args:
            path_points: List of (x, y) coordinates along the routing path
            source_point: (x, y) coordinates of the source endpoint (where wire originates)

        Returns:
            Tuple of (diameter, color) or ('', '') if no spec found
        """
        if not self.wire_specs or len(path_points) < 2:
            return ('', '')

        # Find ALL horizontal segments of the path
        horizontal_segments = []
        for i in range(len(path_points) - 1):
            x1, y1 = path_points[i]
            x2, y2 = path_points[i + 1]

            # Check if this segment is horizontal (Y change < 5 units)
            if abs(y2 - y1) < 5:
                horizontal_segments.append((i, x1, y1, x2, y2))

        # If we know the source point, find the horizontal segment closest to it
        target_segment_points = []
        if source_point and horizontal_segments:
            source_x, source_y = source_point
            min_dist_to_source = float('inf')
            closest_segment = None

            for idx, x1, y1, x2, y2 in horizontal_segments:
                # Distance from source to segment midpoint
                mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
                dist = math.sqrt((mid_x - source_x)**2 + (mid_y - source_y)**2)
                if dist < min_dist_to_source:
                    min_dist_to_source = dist
                    closest_segment = (x1, y1, x2, y2)

            if closest_segment:
                target_segment_points = [(closest_segment[0], closest_segment[1]),
                                        (closest_segment[2], closest_segment[3])]

        # Fallback: use first horizontal segment if no source point provided
        if not target_segment_points and horizontal_segments:
            idx, x1, y1, x2, y2 = horizontal_segments[0]
            target_segment_points = [(x1, y1), (x2, y2)]

        # Fallback: use first few points if no horizontal segments found
        if not target_segment_points:
            target_segment_points = path_points[:min(3, len(path_points))]

        # Find the wire spec closest to the target segment
        # CRITICAL: Only consider specs BETWEEN the segment's X endpoints
        if len(target_segment_points) >= 2:
            seg_x_min = min(p[0] for p in target_segment_points)
            seg_x_max = max(p[0] for p in target_segment_points)
        else:
            seg_x_min, seg_x_max = None, None

        min_distance = float('inf')
        closest_spec = None

        for spec in self.wire_specs:
            # Filter: spec must be STRICTLY between segment's X endpoints
            # (specs are positioned above the wire, not at the ends)
            if seg_x_min is not None and seg_x_max is not None:
                if not (seg_x_min < spec.x < seg_x_max):
                    continue

            # Check distance from spec to each point in the target segment
            for px, py in target_segment_points:
                x_dist = abs(spec.x - px)
                y_dist = spec.y - py  # Negative if spec is above (lower Y)

                # Only consider specs that are ABOVE the path (within 50 Y units above)
                if -50 < y_dist < 0:  # Must be above (spec.y < path.y)
                    # Euclidean distance, strongly prioritize specs directly above (close in Y)
                    # Weight Y-distance MORE to prefer specs just above the wire
                    distance = math.sqrt(x_dist**2 + (y_dist * 2.0)**2)  # Weight Y more

                    if distance < min_distance:
                        min_distance = distance
                        closest_spec = spec

        if closest_spec and min_distance < 150:  # Within 150 units
            return (closest_spec.diameter, closest_spec.color)

        return ('', '')


def deduplicate_connections(connections: List[Connection]) -> List[Connection]:
    """
    Remove duplicate connections and self-loops.

    When duplicates exist (same from/to), prefer the one WITH wire specs.
    This happens when both horizontal wire and routing extractors find the same connection.

    Args:
        connections: List of Connection objects

    Returns:
        List of unique Connection objects
    """
    # CRITICAL: Filter out self-loop connections (connector/splice connecting to itself)
    # Example invalid connections: SP123 → SP123, RRS111,5 → RRS111,5
    # These are caused by arrows pointing to descriptions/labels
    filtered = []
    self_loop_count = 0

    for conn in connections:
        # Check if connection is a self-loop
        is_self_loop = (conn.from_id == conn.to_id and conn.from_pin == conn.to_pin)

        if is_self_loop:
            self_loop_count += 1
            continue

        filtered.append(conn)

    if self_loop_count > 0:
        print(f"Filtered out {self_loop_count} self-loop connections")

    seen = {}  # key -> Connection

    for conn in filtered:
        key = (conn.from_id, conn.from_pin, conn.to_id, conn.to_pin)

        if key not in seen:
            # First time seeing this connection
            seen[key] = conn
        else:
            # Duplicate found - prefer connection WITH wire specs
            existing = seen[key]
            # If new connection has wire spec and existing doesn't, replace
            if conn.wire_dm and not existing.wire_dm:
                seen[key] = conn
            # If existing has wire spec, keep it (don't replace)

    return list(seen.values())
