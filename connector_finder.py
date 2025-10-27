"""
Connector identification and lookup logic.
"""
import re
import math
from typing import List, Optional, Tuple
from models import TextElement, ConnectionPoint


def is_connector_id(text: str) -> bool:
    """
    Check if text is a connector ID (including ground points like G22B(m)).

    Args:
        text: Text to check

    Returns:
        True if text matches connector ID pattern
    """
    # Exclude both labeled (SP001) and custom (SP_CUSTOM_001) splices
    if text.startswith('SP'):
        return False
    # Exclude GND labels (GND, GND1, GND2, etc.) - these are descriptions, not connectors
    if re.match(r'^GND\d*$', text):
        return False
    # Standard connector pattern: MH3202C, FL7210, MH2FL, MAIN557, MAIN38
    # Support 2-4 letter prefixes to handle connectors like MAIN
    if re.match(r'^[A-Z]{2,4}\d{1,5}[A-Z]{0,3}$', text):
        return True
    # Ground point pattern: G22B(m), G05(z), G22_B(m), etc.
    # Allow underscores between letters
    if re.match(r'^[A-Z_]+\d+[A-Z_]*\([a-z]\)$', text):
        return True
    return False


def is_splice_point(text: str) -> bool:
    """
    Check if text is a splice point ID.

    Matches both labeled splice points (SP001, SP023) and
    custom-generated IDs for unlabeled splices (SP_CUSTOM_001).

    Args:
        text: Text to check

    Returns:
        True if text matches splice point pattern (SP* or SP_CUSTOM_*)
    """
    # Match SP001 format
    if re.match(r'^SP\d+$', text):
        return True
    # Match SP_CUSTOM_001 format
    if text.startswith('SP_CUSTOM_'):
        return True
    return False


def is_wire_spec(text: str) -> bool:
    """
    Check if text is a wire specification.

    Args:
        text: Text to check

    Returns:
        True if text matches wire spec pattern (e.g., "0.35,GY/PU")
    """
    return bool(re.match(r'^([\d.]+),([A-Z]{2}(?:/[A-Z]{2})?)$', text))


def parse_wire_spec(text: str) -> Optional[Tuple[str, str]]:
    """
    Parse wire specification into diameter and color.

    Args:
        text: Wire spec text (e.g., "0.35,GY/PU")

    Returns:
        Tuple of (diameter, color) or None if not a wire spec
    """
    match = re.match(r'^([\d.]+),([A-Z]{2}(?:/[A-Z]{2})?)$', text)
    if match:
        return match.group(1), match.group(2)
    return None


def find_connector_above_pin(
    pin_x: float,
    pin_y: float,
    text_elements: List[TextElement],
    prefer_as_source: bool = False,
    source_x: float = None
) -> Optional[Tuple[str, float, float]]:
    """
    Find the closest connector directly above a pin.

    Args:
        pin_x, pin_y: Pin coordinates
        text_elements: List of all text elements
        prefer_as_source: If True, for mirrored junction pairs, prefer the variant where shorter prefix is LAST
                         If False, for mirrored junction pairs, prefer the variant where shorter prefix is FIRST
        source_x: X coordinate of source (for junction selection)

    Returns:
        Tuple of (connector_id, x, y) or None if no connector found
    """
    connectors_above = []

    for elem in text_elements:
        if not is_connector_id(elem.content):
            continue

        # Check if connector is above the pin
        x_dist = abs(elem.x - pin_x)
        y_dist = pin_y - elem.y

        # Connector must be above (positive y_dist) and horizontally aligned
        conn_id = elem.content

        # Detect junction pattern: PREFIX12PREFIX2 (e.g., MH2FL, FL2MH, FTL2FL, FL2FTL)
        # Junction has '2' in middle, splits into two 2-3 letter alphabetic parts
        is_junction = False
        if '2' in conn_id and len(conn_id) >= 5:
            parts = conn_id.split('2', 1)
            if len(parts) == 2 and all(p.isalpha() and 2 <= len(p) <= 3 for p in parts):
                is_junction = True

        max_x_dist = 100 if is_junction else 50

        if x_dist < max_x_dist and y_dist > 5:
            connectors_above.append((y_dist, elem.content, elem.x, elem.y))

    if not connectors_above:
        return None

    # Sort by Y distance first, then X distance for ties
    # Calculate Euclidean distance for final selection
    connectors_with_distance = []
    for y_dist, cid, cx, cy in connectors_above:
        x_dist_from_pin = abs(cx - pin_x)
        euclidean_dist = math.sqrt(y_dist**2 + x_dist_from_pin**2)
        connectors_with_distance.append((euclidean_dist, y_dist, x_dist_from_pin, cid, cx, cy))

    # Sort by Euclidean distance
    connectors_with_distance.sort(key=lambda c: c[0])

    # CRITICAL: If source_x is provided, prefer connectors BETWEEN source and pin
    # This handles shared pins where multiple connectors are above the same pin
    if source_x is not None and not prefer_as_source:
        # Separate connectors into "between" and "not between"
        between_connectors = []
        other_connectors = []

        for conn in connectors_with_distance:
            eucl_dist, y_dist, x_dist, cid, cx, cy = conn

            # Check if connector is between source_x and pin_x
            if source_x < pin_x:
                # Wire goes left to right
                is_between = source_x < cx < pin_x
            else:
                # Wire goes right to left
                is_between = pin_x < cx < source_x

            # CRITICAL: Only prioritize "between" connectors if they're reasonably close in Y
            # This prevents distant connectors from being selected just because they're between in X
            # Use a threshold of 60 Y-units as "reasonable" vertical distance
            if is_between and y_dist < 60:
                between_connectors.append(conn)
            else:
                other_connectors.append(conn)

        # If we have connectors between, prioritize them
        if between_connectors:
            # Use between connectors, sorted by closeness to pin
            connectors_with_distance = between_connectors + other_connectors

    # Check for junction pairs (mirrored connectors like FL2MH/MH2FL, FTL2FL/FL2FTL)
    has_junction_pair = False
    junction_connectors = []
    for c in connectors_with_distance[:3]:
        if '2' in c[3] and len(c[3]) >= 5:
            parts = c[3].split('2', 1)
            if len(parts) == 2 and all(p.isalpha() and 2 <= len(p) <= 3 for p in parts):
                mirror_name = f"{parts[1]}2{parts[0]}"
                if any(c2[3] == mirror_name for c2 in connectors_with_distance[:3]):
                    has_junction_pair = True
                    junction_connectors.append(c)

    # Special handling for junction pairs
    if has_junction_pair and len(junction_connectors) >= 2:
        junc1, junc2 = junction_connectors[0], junction_connectors[1]

        # If we know the source X position, pick the junction that's between source and destination
        if source_x is not None and not prefer_as_source:
            # For destination: pick the junction that's between source_x and pin_x
            junc1_x, junc2_x = junc1[4], junc2[4]

            # Identify junction type for type-specific logic
            is_mh_junction = 'MH2FL' in junc1[3] or 'FL2MH' in junc1[3]

            # Check if wire goes left-to-right or right-to-left
            if source_x < pin_x:
                # Wire goes left to right: pick junction between source and pin
                junc1_between = source_x < junc1_x < pin_x
                junc2_between = source_x < junc2_x < pin_x
            else:
                # Wire goes right to left: pick junction between pin and source
                junc1_between = pin_x < junc1_x < source_x
                junc2_between = pin_x < junc2_x < source_x

            if junc1_between and junc2_between:
                # Both between: logic depends on junction type
                # MH junctions: pick closer to PIN (tightly packed near destination)
                # FTL junctions: pick closer to SOURCE (spread out along wire path)
                if is_mh_junction:
                    dist1_from_pin = abs(junc1_x - pin_x)
                    dist2_from_pin = abs(junc2_x - pin_x)
                    if dist1_from_pin < dist2_from_pin:
                        conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
                    else:
                        conn_id, conn_x, conn_y = junc2[3], junc2[4], junc2[5]
                else:  # FTL junction
                    dist1_from_source = abs(junc1_x - source_x)
                    dist2_from_source = abs(junc2_x - source_x)
                    if dist1_from_source < dist2_from_source:
                        conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
                    else:
                        conn_id, conn_x, conn_y = junc2[3], junc2[4], junc2[5]
            elif junc1_between and not junc2_between:
                # Only junc1 is between: prefer it
                conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
            elif junc2_between and not junc1_between:
                # Only junc2 is between: prefer it
                conn_id, conn_x, conn_y = junc2[3], junc2[4], junc2[5]
            else:
                # Neither between: use closest to pin (junc1 is already sorted as closest)
                conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
        else:
            # No source info or this is source: use closest
            conn_id, conn_x, conn_y = junc1[3], junc1[4], junc1[5]
    else:
        # No junction pair, use closest
        conn_id, conn_x, conn_y = connectors_with_distance[0][3], connectors_with_distance[0][4], connectors_with_distance[0][5]

    return (conn_id, conn_x, conn_y)


def find_connector_above_pin_prefer_ground(
    pin_x: float,
    pin_y: float,
    text_elements: List[TextElement]
) -> Optional[str]:
    """
    Find connector above pin, preferring *2FL variants for ground connections.

    Args:
        pin_x, pin_y: Pin coordinates
        text_elements: List of all text elements

    Returns:
        Connector ID or None
    """
    connectors_above = []

    for elem in text_elements:
        if not is_connector_id(elem.content):
            continue

        x_dist = abs(elem.x - pin_x)
        y_dist = pin_y - elem.y

        is_junction = ('2FL' in elem.content or 'FL2' in elem.content)
        max_x_dist = 100 if is_junction else 50

        if x_dist < max_x_dist and y_dist > 5:
            connectors_above.append((y_dist, elem.content, elem.x, elem.y))

    if not connectors_above:
        return None

    connectors_above.sort(key=lambda c: c[0])

    # CRITICAL: Prefer *2FL pattern (MH2FL, FTL2FL) for ground connections
    to_fl_variants = [c for c in connectors_above if c[1].endswith('2FL')]
    if to_fl_variants:
        return to_fl_variants[0][1]

    # Fall back to closest connector
    return connectors_above[0][1]


def find_nearest_connection_point(
    target_x: float,
    target_y: float,
    text_elements: List[TextElement],
    max_distance: float = 100
) -> Optional[ConnectionPoint]:
    """
    Find the nearest pin or splice point to a target coordinate.

    Used for vertical routing where polyline endpoints may not exactly align.

    Args:
        target_x, target_y: Target coordinates
        text_elements: List of all text elements
        max_distance: Maximum distance to search

    Returns:
        ConnectionPoint or None
    """
    nearest = None
    min_distance = float('inf')

    for elem in text_elements:
        # Check for pin numbers (digits), splice points (SP*), or ground connectors
        is_ground = is_connector_id(elem.content) and '(' in elem.content
        if elem.content.isdigit() or is_splice_point(elem.content) or is_ground:
            dist = math.sqrt((elem.x - target_x)**2 + (elem.y - target_y)**2)

            if dist < max_distance and dist < min_distance:
                min_distance = dist

                if is_splice_point(elem.content):
                    # It's a splice point
                    nearest = ConnectionPoint(elem.content, '', elem.x, elem.y)
                elif is_ground:
                    # It's a ground connector
                    nearest = ConnectionPoint(elem.content, '', elem.x, elem.y)
                else:
                    # It's a pin number - find the connector above it
                    connector_result = find_connector_above_pin(elem.x, elem.y, text_elements)
                    if connector_result:
                        nearest = ConnectionPoint(
                            connector_result[0],
                            elem.content,
                            elem.x,
                            elem.y
                        )

    return nearest


def find_all_connectors_above_pin(
    pin_x: float,
    pin_y: float,
    text_elements: List[TextElement]
) -> List[Tuple[float, str, float, float]]:
    """
    Find ALL connectors above a pin (not just the closest).

    Used for ground connections where we need to choose between junction variants.

    Args:
        pin_x, pin_y: Pin coordinates
        text_elements: List of all text elements

    Returns:
        List of (y_distance, connector_id, x, y) tuples, sorted by Y distance
    """
    connectors_above = []

    for elem in text_elements:
        if not is_connector_id(elem.content):
            continue

        x_dist = abs(elem.x - pin_x)
        y_dist = pin_y - elem.y

        is_junction = ('2FL' in elem.content or 'FL2' in elem.content)
        max_x_dist = 100 if is_junction else 50

        if x_dist < max_x_dist and y_dist > 5:
            connectors_above.append((y_dist, elem.content, elem.x, elem.y))

    connectors_above.sort(key=lambda c: c[0])
    return connectors_above
