"""
SVG parsing utilities for circuit diagrams.
"""
import re
import xml.etree.ElementTree as ET
from typing import List, Tuple
from models import TextElement, WireSpec


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

    Splice dots are represented as path elements starting with "M x,y c".

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
        # Parse circle paths (splice dots): M x,y c ...
        match = re.match(r'M([\d.]+),([\d.]+)c', d)
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
    max_distance: float = 20
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
    import math
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
