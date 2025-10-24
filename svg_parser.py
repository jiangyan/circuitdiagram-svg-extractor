"""
SVG parsing utilities for circuit diagrams.
"""
import re
import math
import xml.etree.ElementTree as ET
from typing import List, Tuple
from models import TextElement, WireSpec, IDGenerator


def parse_text_elements(svg_file: str) -> List[TextElement]:
    """
    Parse all text elements from SVG file.

    Args:
        svg_file: Path to SVG file

    Returns:
        List of TextElement objects
    """
    tree = ET.parse(svg_file)
    root = tree.getroot()

    text_elements = []

    for text in root.iter('{http://www.w3.org/2000/svg}text'):
        transform = text.get('transform', '')
        content = text.text

        if not transform or not content:
            continue

        # Extract coordinates from transform matrix
        # Format: "matrix(1 0 0 1 237.3564 331.6939)"
        match = re.search(r'matrix\([^\)]+\s+([\d.]+)\s+([\d.]+)\)', transform)
        if match:
            x = float(match.group(1))
            y = float(match.group(2))
            text_elements.append(TextElement(content.strip(), x, y))

    return text_elements


def parse_splice_dots(svg_file: str) -> List[Tuple[float, float]]:
    """
    Parse splice point dots from SVG.

    Splice dots are small circles drawn with cubic bezier curves.
    Pattern: M x,y c ... (short path with multiple 'c' commands forming a circle)

    Args:
        svg_file: Path to SVG file

    Returns:
        List of (x, y) coordinates
    """
    tree = ET.parse(svg_file)
    root = tree.getroot()

    dots = []

    for path in root.iter('{http://www.w3.org/2000/svg}path'):
        d = path.get('d', '')

        # Splice dots are circles with these characteristics:
        # 1. No class attribute (real splice dots have no styling)
        # 2. Short path (< 200 chars)
        # 3. Multiple cubic bezier curves (at least 3 'c' commands)
        # 4. Starts with M x,y

        # CRITICAL: Only match paths with no class attribute
        # This excludes arrowheads (st10), routing arrows (st17), and other styled elements
        if path.get('class'):
            continue

        if len(d) > 200:
            continue

        # Count 'c' commands (cubic bezier curves)
        c_count = d.count('c') + d.count('C')
        # Rough heuristic: path('d="...c...c...c..."') has 3+ c's for circles
        if c_count < 3:
            continue

        # Extract starting coordinates
        match = re.match(r'M([\d.]+),([\d.]+)', d)
        if match:
            x = float(match.group(1))
            y = float(match.group(2))
            dots.append((x, y))

    return dots


def parse_wire_lines(svg_file: str) -> List[Tuple[float, float, float, float]]:
    """
    Parse horizontal wire lines from SVG.

    Args:
        svg_file: Path to SVG file

    Returns:
        List of (x1, y1, x2, y2) tuples
    """
    tree = ET.parse(svg_file)
    root = tree.getroot()

    lines = []

    for line in root.iter('{http://www.w3.org/2000/svg}line'):
        x1 = line.get('x1')
        y1 = line.get('y1')
        x2 = line.get('x2')
        y2 = line.get('y2')

        if x1 and y1 and x2 and y2:
            lines.append((float(x1), float(y1), float(x2), float(y2)))

    return lines


def parse_st17_polylines(svg_file: str) -> List[str]:
    """
    Parse st17 polyline elements (vertical routing arrows).

    Args:
        svg_file: Path to SVG file

    Returns:
        List of points strings (e.g., "x1,y1 x2,y2 x3,y3")
    """
    tree = ET.parse(svg_file)
    root = tree.getroot()

    polylines = []

    for polyline in root.iter('{http://www.w3.org/2000/svg}polyline'):
        if polyline.get('class', '') == 'st17':
            points = polyline.get('points', '').strip()
            if points:
                polylines.append(points)

    return polylines


def parse_all_polylines(svg_file: str) -> List[str]:
    """
    Parse ALL polyline elements (for routing connections).

    This includes st17 (vertical routing), st3/st4 (diagonal routing to confluence points),
    and any other polyline-based wire connections.

    Args:
        svg_file: Path to SVG file

    Returns:
        List of points strings (e.g., "x1,y1 x2,y2 x3,y3")
    """
    tree = ET.parse(svg_file)
    root = tree.getroot()

    polylines = []

    for polyline in root.iter('{http://www.w3.org/2000/svg}polyline'):
        points = polyline.get('points', '').strip()
        if points:
            polylines.append(points)

    return polylines


def parse_st17_paths(svg_file: str) -> List[str]:
    """
    Parse st17 path elements (ground connection arrows).

    Args:
        svg_file: Path to SVG file

    Returns:
        List of d attribute strings
    """
    tree = ET.parse(svg_file)
    root = tree.getroot()

    paths = []

    for path in root.iter('{http://www.w3.org/2000/svg}path'):
        if path.get('class', '') == 'st17':
            d = path.get('d', '').strip()
            if d:
                paths.append(d)

    return paths


def parse_st1_paths(svg_file: str) -> List[str]:
    """
    Parse st1 path elements (white routing wires).

    Args:
        svg_file: Path to SVG file

    Returns:
        List of d attribute strings
    """
    tree = ET.parse(svg_file)
    root = tree.getroot()

    paths = []

    for path in root.iter('{http://www.w3.org/2000/svg}path'):
        if path.get('class', '') == 'st1':
            d = path.get('d', '').strip()
            if d:
                paths.append(d)

    return paths


def parse_routing_paths(svg_file: str, path_classes: List[str] = None) -> List[str]:
    """
    Parse routing path elements by class names.

    Args:
        svg_file: Path to SVG file
        path_classes: List of class names to parse (e.g., ['st3', 'st4'])
                     If None, defaults to ['st3', 'st4']

    Returns:
        List of d attribute strings
    """
    if path_classes is None:
        path_classes = ['st3', 'st4']

    tree = ET.parse(svg_file)
    root = tree.getroot()

    paths = []

    for path in root.iter('{http://www.w3.org/2000/svg}path'):
        cls = path.get('class', '')
        if cls in path_classes:
            d = path.get('d', '').strip()
            if d:
                paths.append(d)

    return paths


def extract_path_all_points(d_attr: str) -> list:
    """
    Extract all significant points from an SVG path d attribute.

    Returns a list of (x, y) tuples representing all points along the path.

    Args:
        d_attr: SVG path d attribute string

    Returns:
        List of (x, y) tuples, or empty list if parsing fails
    """
    import re

    try:
        commands = re.findall(r'[MmLlHhVvCcSsQqTtAaZz][^MmLlHhVvCcSsQqTtAaZz]*', d_attr)

        if not commands:
            return []

        # Parse first command (should be M or m)
        first_cmd = commands[0].strip()
        if first_cmd[0] not in ['M', 'm']:
            return []

        # Extract start coordinates from M command
        coords = re.findall(r'-?\d+\.?\d*', first_cmd)
        if len(coords) < 2:
            return []

        start_x, start_y = float(coords[0]), float(coords[1])
        current_x, current_y = start_x, start_y

        points = [(current_x, current_y)]

        # Process subsequent commands
        for cmd_str in commands[1:]:
            cmd = cmd_str[0]
            params = re.findall(r'-?\d+\.?\d*', cmd_str[1:])

            if cmd == 'M':  # Absolute moveto
                if len(params) >= 2:
                    current_x, current_y = float(params[0]), float(params[1])
                    points.append((current_x, current_y))
            elif cmd == 'm':  # Relative moveto
                if len(params) >= 2:
                    current_x += float(params[0])
                    current_y += float(params[1])
                    points.append((current_x, current_y))
            elif cmd == 'L':  # Absolute lineto
                if len(params) >= 2:
                    current_x, current_y = float(params[-2]), float(params[-1])
                    points.append((current_x, current_y))
            elif cmd == 'l':  # Relative lineto
                if len(params) >= 2:
                    current_x += float(params[-2])
                    current_y += float(params[-1])
                    points.append((current_x, current_y))
            elif cmd == 'H':  # Absolute horizontal
                if len(params) >= 1:
                    current_x = float(params[-1])
                    points.append((current_x, current_y))
            elif cmd == 'h':  # Relative horizontal
                if len(params) >= 1:
                    current_x += float(params[-1])
                    points.append((current_x, current_y))
            elif cmd == 'V':  # Absolute vertical
                if len(params) >= 1:
                    current_y = float(params[-1])
                    points.append((current_x, current_y))
            elif cmd == 'v':  # Relative vertical
                if len(params) >= 1:
                    current_y += float(params[-1])
                    points.append((current_x, current_y))
            elif cmd == 'C':  # Absolute cubic bezier
                if len(params) >= 6:
                    current_x, current_y = float(params[-2]), float(params[-1])
                    points.append((current_x, current_y))
            elif cmd == 'c':  # Relative cubic bezier
                if len(params) >= 6:
                    current_x += float(params[-2])
                    current_y += float(params[-1])
                    points.append((current_x, current_y))
            elif cmd in ['Z', 'z']:  # Close path
                current_x, current_y = start_x, start_y
                points.append((current_x, current_y))

        return points

    except Exception:
        return []


def extract_path_endpoints(d_attr: str) -> tuple:
    """
    Extract start and end coordinates from an SVG path d attribute.

    Supports basic path commands: M (moveto), L/l (lineto), H/h (horizontal),
    V/v (vertical), C/c (cubic bezier), and Z/z (closepath).

    Args:
        d_attr: SVG path d attribute string

    Returns:
        Tuple of (start_x, start_y, end_x, end_y) or None if parsing fails
    """
    import re

    try:
        # Remove extra whitespace and split by command letters
        commands = re.findall(r'[MmLlHhVvCcSsQqTtAaZz][^MmLlHhVvCcSsQqTtAaZz]*', d_attr)

        if not commands:
            return None

        # Parse first command (should be M or m)
        first_cmd = commands[0].strip()
        if first_cmd[0] not in ['M', 'm']:
            return None

        # Extract start coordinates from M command
        coords = re.findall(r'-?\d+\.?\d*', first_cmd)
        if len(coords) < 2:
            return None

        start_x, start_y = float(coords[0]), float(coords[1])
        current_x, current_y = start_x, start_y

        # Process subsequent commands to find end point
        for cmd_str in commands[1:]:
            cmd = cmd_str[0]
            params = re.findall(r'-?\d+\.?\d*', cmd_str[1:])

            if cmd == 'M':  # Absolute moveto
                if len(params) >= 2:
                    current_x, current_y = float(params[0]), float(params[1])
            elif cmd == 'm':  # Relative moveto
                if len(params) >= 2:
                    current_x += float(params[0])
                    current_y += float(params[1])
            elif cmd == 'L':  # Absolute lineto
                if len(params) >= 2:
                    current_x, current_y = float(params[-2]), float(params[-1])
            elif cmd == 'l':  # Relative lineto
                if len(params) >= 2:
                    current_x += float(params[-2])
                    current_y += float(params[-1])
            elif cmd == 'H':  # Absolute horizontal
                if len(params) >= 1:
                    current_x = float(params[-1])
            elif cmd == 'h':  # Relative horizontal
                if len(params) >= 1:
                    current_x += float(params[-1])
            elif cmd == 'V':  # Absolute vertical
                if len(params) >= 1:
                    current_y = float(params[-1])
            elif cmd == 'v':  # Relative vertical
                if len(params) >= 1:
                    current_y += float(params[-1])
            elif cmd == 'C':  # Absolute cubic bezier
                if len(params) >= 6:
                    current_x, current_y = float(params[-2]), float(params[-1])
            elif cmd == 'c':  # Relative cubic bezier
                if len(params) >= 6:
                    current_x += float(params[-2])
                    current_y += float(params[-1])
            elif cmd in ['Z', 'z']:  # Close path
                current_x, current_y = start_x, start_y

        return (start_x, start_y, current_x, current_y)

    except Exception:
        return None


def extract_wire_specs(text_elements: List[TextElement]) -> List[WireSpec]:
    """
    Extract wire specifications from text elements.

    Args:
        text_elements: List of TextElement objects

    Returns:
        List of WireSpec objects
    """
    from connector_finder import is_wire_spec, parse_wire_spec

    wire_specs = []

    for elem in text_elements:
        if is_wire_spec(elem.content):
            parsed = parse_wire_spec(elem.content)
            if parsed:
                diameter, color = parsed
                wire_specs.append(WireSpec(diameter, color, elem.x, elem.y))

    return wire_specs


def map_splice_positions_to_dots(
    text_elements: List[TextElement],
    dots: List[Tuple[float, float]],
    max_distance: float = 35
) -> List[TextElement]:
    """
    Map splice point labels (SP*) to their dot positions.

    Some splice points have labels offset from their actual position.
    This function corrects the position by finding the nearest dot.

    Args:
        text_elements: List of TextElement objects
        dots: List of dot (x, y) coordinates
        max_distance: Maximum distance to consider

    Returns:
        List of TextElement objects with corrected positions
    """
    from connector_finder import is_splice_point

    corrected_elements = []

    for elem in text_elements:
        if is_splice_point(elem.content):
            # Find nearest dot
            nearest_dot = None
            min_dist = float('inf')

            for dot_x, dot_y in dots:
                dist = math.sqrt((elem.x - dot_x)**2 + (elem.y - dot_y)**2)
                if dist < max_distance and dist < min_dist:
                    min_dist = dist
                    nearest_dot = (dot_x, dot_y)

            if nearest_dot:
                # Use dot position instead of label position
                corrected_elements.append(
                    TextElement(elem.content, nearest_dot[0], nearest_dot[1])
                )
            else:
                # Keep original position
                corrected_elements.append(elem)
        else:
            # Not a splice point - keep as is
            corrected_elements.append(elem)

    return corrected_elements


def generate_ids_for_unlabeled_splices(
    text_elements: List[TextElement],
    dots: List[Tuple[float, float]],
    id_generator: IDGenerator,
    max_distance: float = 35
) -> List[TextElement]:
    """
    Generate custom IDs for splice dots that don't have labels.

    This handles edge cases where circuit diagrams contain splice points (dots)
    without accompanying SP* labels. Custom IDs are generated in format SP_CUSTOM_001.

    Args:
        text_elements: Existing text elements (should already be mapped to dots)
        dots: All splice dot positions from parse_splice_dots()
        id_generator: IDGenerator instance for creating custom IDs
        max_distance: Maximum distance to consider a label as associated with a dot (default: 35)

    Returns:
        Augmented list of text elements including generated IDs for unlabeled dots
    """
    from connector_finder import is_splice_point

    # Collect all labeled splice positions (after map_splice_positions_to_dots)
    labeled_positions = []
    for elem in text_elements:
        if is_splice_point(elem.content):
            labeled_positions.append((elem.x, elem.y))

    # Find unlabeled dots
    unlabeled_dots = []
    for dot_x, dot_y in dots:
        # Check if this dot has a label positioned on or very near it
        has_label = False
        for label_x, label_y in labeled_positions:
            dist = math.sqrt((dot_x - label_x)**2 + (dot_y - label_y)**2)
            if dist < max_distance:
                has_label = True
                break

        if not has_label:
            unlabeled_dots.append((dot_x, dot_y))

    # Generate IDs for unlabeled dots
    result = list(text_elements)  # Copy existing elements

    if unlabeled_dots:
        print(f"Found {len(unlabeled_dots)} unlabeled splice dots - generating custom IDs")

    for dot_x, dot_y in unlabeled_dots:
        custom_id = id_generator.get_or_create_splice_id(dot_x, dot_y)
        result.append(TextElement(custom_id, dot_x, dot_y))
        print(f"  Generated {custom_id} at ({dot_x:.1f}, {dot_y:.1f})")

    return result
