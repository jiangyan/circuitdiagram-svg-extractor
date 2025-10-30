"""
Long routing connection extractor.

Extracts long-distance splice-to-splice routing connections based on wire color flow analysis.
Uses wire color continuity logic: if a splice has incoming wires of a specific color but no
outgoing connections for that color, it must route to another splice with the same color.

This handles long vertical/diagonal routing wires that are not captured by polylines or paths.
"""
import math
from typing import List
from models import Connection, TextElement
from connector_finder import is_splice_point
from .base_extractor import deduplicate_connections


class LongRoutingConnectionExtractor:
    """
    Extracts long-distance splice-to-splice routing connections based on wire color flow analysis.

    Uses wire color continuity logic: if a splice has incoming wires of a specific color but no
    outgoing connections for that color, it must route to another splice with the same color.

    This handles long vertical/diagonal routing wires that are not captured by polylines or paths.
    """

    def __init__(self, existing_connections: List[Connection], text_elements: List[TextElement]):
        """
        Initialize the extractor with existing connections and text elements.

        Args:
            existing_connections: All connections from horizontal and routing extractors
            text_elements: All text elements (to get splice positions)
        """
        self.existing_connections = existing_connections
        self.text_elements = text_elements

        # Build splice position map
        self.splice_positions = {}
        for elem in text_elements:
            if is_splice_point(elem.content):
                self.splice_positions[elem.content] = (elem.x, elem.y)

    def _analyze_wire_flow(self) -> dict:
        """
        Analyze wire flow through each splice point.

        Returns:
            Dictionary mapping splice_id -> wire_key -> {'incoming': count, 'outgoing': count}
        """
        splice_wire_flow = {}

        for conn in self.existing_connections:
            # Skip connections without wire specs
            if not conn.wire_dm or not conn.wire_color:
                continue

            wire_key = f'{conn.wire_dm},{conn.wire_color}'

            # Track outgoing from source splice
            if is_splice_point(conn.from_id):
                if conn.from_id not in splice_wire_flow:
                    splice_wire_flow[conn.from_id] = {}
                if wire_key not in splice_wire_flow[conn.from_id]:
                    splice_wire_flow[conn.from_id][wire_key] = {'incoming': 0, 'outgoing': 0}
                splice_wire_flow[conn.from_id][wire_key]['outgoing'] += 1

            # Track incoming to destination splice
            if is_splice_point(conn.to_id):
                if conn.to_id not in splice_wire_flow:
                    splice_wire_flow[conn.to_id] = {}
                if wire_key not in splice_wire_flow[conn.to_id]:
                    splice_wire_flow[conn.to_id][wire_key] = {'incoming': 0, 'outgoing': 0}
                splice_wire_flow[conn.to_id][wire_key]['incoming'] += 1

        return splice_wire_flow

    def _connection_exists(self, from_sp: str, to_sp: str) -> bool:
        """Check if a connection already exists between two splices (in either direction)."""
        return any(
            (conn.from_id == from_sp and conn.to_id == to_sp) or
            (conn.from_id == to_sp and conn.to_id == from_sp)
            for conn in self.existing_connections
        )

    def _distance(self, sp1: str, sp2: str) -> float:
        """Calculate Euclidean distance between two splices."""
        if sp1 not in self.splice_positions or sp2 not in self.splice_positions:
            return float('inf')

        pos1 = self.splice_positions[sp1]
        pos2 = self.splice_positions[sp2]
        return math.sqrt((pos1[0] - pos2[0])**2 + (pos1[1] - pos2[1])**2)

    def extract_connections(self) -> List[Connection]:
        """
        Extract long routing connections based on wire color flow analysis.

        Returns:
            List of Connection objects for long routing wires
        """
        connections = []
        seen_pairs = set()  # Track (splice_a, splice_b) pairs to prevent reverse duplicates

        # Step 1: Analyze wire flow through all splices
        splice_wire_flow = self._analyze_wire_flow()

        # Step 2: Find splices with unbalanced wire flow (more incoming than outgoing)
        needs_outgoing = {}  # wire_key -> [(splice_id, excess_count)]

        for splice_id, wire_flows in splice_wire_flow.items():
            for wire_key, flow in wire_flows.items():
                balance = flow['incoming'] - flow['outgoing']

                if balance > 0:  # More incoming than outgoing - needs routing
                    if wire_key not in needs_outgoing:
                        needs_outgoing[wire_key] = []
                    needs_outgoing[wire_key].append((splice_id, balance))

        # Step 3: For each unbalanced splice, find matching destination splices
        for wire_key in needs_outgoing:
            splices_needing_route = needs_outgoing[wire_key]

            for source_sp, excess_count in splices_needing_route:
                # Check if this splice has already been used as a destination in a pair
                # This prevents reverse connections (if SP198→SP250 exists, skip SP250→SP198)
                already_paired = any(
                    source_sp in pair for pair in seen_pairs
                )
                if already_paired:
                    continue

                # Find candidate destination splices with the same wire color
                candidates = []

                for dest_sp, dest_flows in splice_wire_flow.items():
                    # Skip self
                    if dest_sp == source_sp:
                        continue

                    # Must have the same wire color
                    if wire_key not in dest_flows:
                        continue

                    # CRITICAL: Validate source splice doesn't have conflicting dominant color
                    # If source has 3 BU/BK connections and 1 PU/OG connection, the PU/OG is likely false
                    # Only create connection if this wire_key is the dominant or equal color for source
                    source_flows = splice_wire_flow.get(source_sp, {})
                    if len(source_flows) > 1:  # Splice has multiple colors
                        # Count total connections for each color
                        color_totals = {k: v['incoming'] + v['outgoing'] for k, v in source_flows.items()}
                        max_count = max(color_totals.values())
                        current_count = color_totals.get(wire_key, 0)

                        # Skip if this color is significantly less than the dominant color
                        # (e.g., 1 connection vs 3+ connections for another color)
                        if current_count < max_count and current_count <= 1:
                            continue

                    # Check if pair already processed (either direction)
                    pair_key = tuple(sorted([source_sp, dest_sp]))
                    if pair_key in seen_pairs:
                        continue

                    # Skip if connection already exists in base connections
                    if self._connection_exists(source_sp, dest_sp):
                        continue

                    # Calculate distance and direction
                    dist = self._distance(source_sp, dest_sp)

                    # CRITICAL: Only consider long-distance routing (> 400 units)
                    # This filters out local junctions and focuses on cross-diagram routing
                    if dist <= 400:
                        continue

                    # Calculate direction vector
                    pos_src = self.splice_positions[source_sp]
                    pos_dst = self.splice_positions[dest_sp]
                    delta_x = pos_dst[0] - pos_src[0]
                    delta_y = pos_dst[1] - pos_src[1]

                    # CRITICAL: Prefer routing with significant vertical component (ΔY > 200)
                    # Long routing wires typically have both horizontal and vertical segments
                    if abs(delta_y) <= 200:
                        continue

                    candidates.append((dest_sp, dist, delta_x, delta_y))

                if not candidates:
                    continue

                # Sort candidates by distance (prefer closer ones)
                candidates.sort(key=lambda x: x[1])

                # Create connection to the closest matching splice
                # Parse wire_key to get diameter and color
                diameter, color = wire_key.split(',')
                dest_sp, dist, delta_x, delta_y = candidates[0]

                # Mark this pair as seen to prevent reverse connection
                pair_key = tuple(sorted([source_sp, dest_sp]))
                seen_pairs.add(pair_key)

                connections.append(Connection(
                    from_id=source_sp,
                    from_pin='',  # Splices don't have pins
                    to_id=dest_sp,
                    to_pin='',
                    wire_dm=diameter,
                    wire_color=color
                ))

        return deduplicate_connections(connections)
