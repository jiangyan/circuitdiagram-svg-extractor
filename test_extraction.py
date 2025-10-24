"""
Test suite for circuit diagram connection extraction.

Validates extraction logic against golden standard test cases.

Usage:
    python test_extraction.py           # Run all tests
    python test_extraction.py -v        # Verbose mode

How it works:
    1. Loads expected connections from connections_output.md (golden standard)
    2. Runs extraction on sample-wire.svg
    3. Compares actual vs expected connections
    4. Reports pass/fail with detailed differences

Golden Standard:
    - File: sample-wire.svg
    - Expected: 54 connections
    - Source: connections_output.md (baseline that must always pass)

Adding New Test Cases:
    1. Create a new SVG file in test_cases/ directory
    2. Manually verify expected connections
    3. Add test case in main():

        new_test = TestCase(
            name="Edge Case: Description",
            svg_file="test_cases/your_file.svg",
            expected_connections=[
                ('FROM', 'PIN', 'TO', 'PIN', 'DM', 'COLOR'),
                # ... more connections
            ]
        )
        tester.add_test_case(new_test)

    4. Run: python test_extraction.py

Why This Matters:
    - Prevents regressions when adding new features
    - Documents expected behavior for each edge case
    - Enables confident refactoring of extraction logic
    - Each new diagram becomes a permanent validation test
"""
import sys
from typing import List, Set, Tuple
from models import Connection, IDGenerator
from svg_parser import (
    parse_text_elements,
    parse_splice_dots,
    parse_st17_polylines,
    parse_all_polylines,
    parse_st17_paths,
    parse_st1_paths,
    extract_wire_specs,
    map_splice_positions_to_dots,
    generate_ids_for_unlabeled_splices
)
from extractors import (
    HorizontalWireExtractor,
    VerticalRoutingExtractor,
    GroundConnectionExtractor,
    deduplicate_connections
)


class TestCase:
    """A test case with SVG file and expected connections."""

    def __init__(self, name: str, svg_file: str, expected_connections: List[Tuple]):
        self.name = name
        self.svg_file = svg_file
        self.expected_connections = expected_connections

    def __repr__(self):
        return f"TestCase('{self.name}', connections={len(self.expected_connections)})"


class ExtractionTester:
    """Tests connection extraction against golden standards."""

    def __init__(self):
        self.test_cases: List[TestCase] = []
        self.verbose = False

    def add_test_case(self, test_case: TestCase):
        """Add a test case to the suite."""
        self.test_cases.append(test_case)

    def extract_connections(self, svg_file: str) -> List[Connection]:
        """Run extraction on a file (with unlabeled splice ID generation)."""
        # Initialize ID generator
        id_generator = IDGenerator()

        # Parse SVG
        text_elements = parse_text_elements(svg_file)
        splice_dots = parse_splice_dots(svg_file)
        polylines = parse_all_polylines(svg_file)  # Use all polylines for diagonal routing
        st17_paths = parse_st17_paths(svg_file)
        st1_paths = parse_st1_paths(svg_file)

        # Map splice positions
        text_elements = map_splice_positions_to_dots(text_elements, splice_dots)

        # Generate IDs for unlabeled splices
        text_elements = generate_ids_for_unlabeled_splices(text_elements, splice_dots, id_generator)

        # Extract wire specs
        wire_specs = extract_wire_specs(text_elements)

        # Run extractors
        horizontal_extractor = HorizontalWireExtractor(text_elements, wire_specs)
        horizontal_connections = horizontal_extractor.extract_connections()

        vertical_extractor = VerticalRoutingExtractor(polylines, st1_paths, text_elements)
        vertical_connections = vertical_extractor.extract_connections()

        ground_extractor = GroundConnectionExtractor(st17_paths, text_elements)
        ground_connections = ground_extractor.extract_connections()

        # Combine and deduplicate globally
        combined = horizontal_connections + vertical_connections + ground_connections
        return deduplicate_connections(combined)

    def connection_to_tuple(self, conn: Connection) -> Tuple:
        """Convert Connection to comparable tuple."""
        return (
            conn.from_id,
            conn.from_pin,
            conn.to_id,
            conn.to_pin,
            conn.wire_dm,
            conn.wire_color
        )

    def compare_connections(
        self,
        actual: List[Connection],
        expected: List[Tuple]
    ) -> Tuple[bool, str]:
        """
        Compare actual connections against expected.

        Returns:
            (success: bool, message: str)
        """
        # Convert to sets of tuples for comparison
        actual_set = {self.connection_to_tuple(c) for c in actual}
        expected_set = set(expected)

        # Check counts
        if len(actual_set) != len(expected_set):
            return False, f"Count mismatch: got {len(actual_set)}, expected {len(expected_set)}"

        # Find differences
        missing = expected_set - actual_set
        extra = actual_set - expected_set

        if missing or extra:
            msg = []
            if missing:
                msg.append(f"Missing {len(missing)} connections:")
                for conn in list(missing)[:5]:  # Show first 5
                    msg.append(f"  - {conn[0]} pin {conn[1]} → {conn[2]} pin {conn[3]}")
            if extra:
                msg.append(f"Extra {len(extra)} connections:")
                for conn in list(extra)[:5]:  # Show first 5
                    msg.append(f"  + {conn[0]} pin {conn[1]} → {conn[2]} pin {conn[3]}")
            return False, "\n".join(msg)

        return True, "All connections match!"

    def run_test(self, test_case: TestCase) -> bool:
        """Run a single test case."""
        print(f"\n{'='*80}")
        print(f"Running: {test_case.name}")
        print(f"{'='*80}")

        try:
            # Extract connections
            actual_connections = self.extract_connections(test_case.svg_file)

            if self.verbose:
                print(f"Extracted {len(actual_connections)} connections")

            # Compare
            success, message = self.compare_connections(
                actual_connections,
                test_case.expected_connections
            )

            if success:
                print(f"✓ PASS: {message}")
                return True
            else:
                print(f"✗ FAIL: {message}")
                return False

        except Exception as e:
            print(f"✗ ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

    def run_all_tests(self) -> bool:
        """Run all test cases."""
        print("\n" + "="*80)
        print("CIRCUIT DIAGRAM EXTRACTION TEST SUITE")
        print("="*80)
        print(f"Running {len(self.test_cases)} test case(s)...")

        results = []
        for test_case in self.test_cases:
            results.append(self.run_test(test_case))

        # Summary
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)

        passed = sum(results)
        failed = len(results) - passed

        print(f"Total:  {len(results)}")
        print(f"Passed: {passed} ✓")
        print(f"Failed: {failed} ✗")

        if all(results):
            print("\n🎉 ALL TESTS PASSED!")
            return True
        else:
            print("\n❌ SOME TESTS FAILED")
            return False


def load_golden_standard() -> List[Tuple]:
    """
    Load golden standard connections from connections_output.md.

    Parses the markdown table and returns list of connection tuples.
    """
    connections = []

    with open('connections_output.md', 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Find the table section
    in_table = False
    for line in lines:
        line = line.strip()

        # Start of connections table
        if line.startswith('| From | From Pin |'):
            in_table = True
            continue

        # Skip header separator
        if line.startswith('|---'):
            continue

        # End of table (blank line or new section)
        if in_table and (not line or line.startswith('#')):
            break

        # Parse connection row
        if in_table and line.startswith('|'):
            parts = [p.strip() for p in line.split('|')]
            # Format: | From | From Pin | To | To Pin | Wire DM | Color |
            # Index:    0      1          2    3        4         5       6
            if len(parts) >= 7:
                from_id = parts[1]
                from_pin = parts[2]
                to_id = parts[3]
                to_pin = parts[4]
                wire_dm = parts[5]
                wire_color = parts[6]

                connections.append((from_id, from_pin, to_id, to_pin, wire_dm, wire_color))

    return connections


def create_baseline_test_case() -> TestCase:
    """Create the baseline test case from sample-wire.svg."""
    expected = load_golden_standard()

    return TestCase(
        name="Baseline: sample-wire.svg",
        svg_file="sample-wire.svg",
        expected_connections=expected
    )


def main():
    """Run the test suite."""
    # Create tester
    tester = ExtractionTester()
    tester.verbose = '--verbose' in sys.argv or '-v' in sys.argv

    # Add baseline test
    baseline = create_baseline_test_case()
    tester.add_test_case(baseline)

    print(f"Loaded golden standard: {len(baseline.expected_connections)} connections")

    # Run tests
    success = tester.run_all_tests()

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
