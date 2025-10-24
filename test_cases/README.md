# Test Cases Directory

This directory contains SVG files for edge case testing.

## Purpose

Each SVG file in this directory represents a specific edge case or scenario that needs validation. As we encounter new diagram patterns, we add them here with expected results.

## Directory Structure

```
test_cases/
├── README.md                    # This file
├── unnamed_splices.svg          # Example: Unnamed splice points
├── unnamed_connectors.svg       # Example: Unnamed connectors
├── multi_segment_routing.svg    # Example: Complex routing
└── ... more edge cases
```

## Adding a New Test Case

### 1. Prepare the SVG File

- Export from Adobe Illustrator as SVG
- Name it descriptively (e.g., `unnamed_splices.svg`)
- Place it in this directory

### 2. Manually Verify Expected Connections

Run the extractor and manually verify the results:

```bash
# Temporarily modify extract_connections.py to use your test file
python extract_connections.py
```

Review `connections_output.md` and verify each connection is correct.

### 3. Add Test Case to test_extraction.py

```python
def main():
    tester = ExtractionTester()

    # Baseline test
    baseline = create_baseline_test_case()
    tester.add_test_case(baseline)

    # Add your new test case
    edge_case = TestCase(
        name="Edge Case: Unnamed Splice Points",
        svg_file="test_cases/unnamed_splices.svg",
        expected_connections=[
            ('MH3202C', '25', 'SP_CUSTOM_001', '', '0.35', 'WH/RD'),
            ('MH3202C', '26', 'SP_CUSTOM_002', '', '0.35', 'BU/BK'),
            # ... all expected connections
        ]
    )
    tester.add_test_case(edge_case)

    tester.run_all_tests()
```

### 4. Run Tests

```bash
python test_extraction.py
```

Expected output:
```
Running 2 test case(s)...
✓ PASS: Baseline: sample-wire.svg
✓ PASS: Edge Case: Unnamed Splice Points
🎉 ALL TESTS PASSED!
```

## Edge Case Categories

### Current Test Cases

1. **Baseline** (`sample-wire.svg`)
   - Standard diagram with all features
   - 54 connections (48 horizontal + 5 vertical + 1 ground)
   - Junction connectors, splice points, ground symbols

### Planned Edge Cases

- **Unnamed splice points** - Splices without SP* labels (need custom ID generation)
- **Unnamed connectors** - Connectors without labels (need custom ID generation)
- **Dense pin layouts** - Many pins in tight spaces
- **Overlapping wires** - Multiple wire specs on same line
- **Multi-segment routing** - Complex polyline paths with multiple splices
- **Mixed junction types** - Multiple junction pairs in one area
- **Unusual ground symbols** - Different ground connector patterns
- **Very long wires** - Connections spanning large distances
- **Compact diagrams** - High density of components

## Test Case Template

When adding a new test case, document it:

```markdown
### Edge Case: [Name]

**File:** `test_cases/[filename].svg`

**Scenario:** [Description of what this tests]

**Key Features:**
- [Feature 1]
- [Feature 2]

**Expected Behavior:**
- [Expected output 1]
- [Expected output 2]

**Validation Points:**
- [ ] All connections extracted correctly
- [ ] Custom IDs generated as expected
- [ ] No duplicate connections
- [ ] Proper junction handling
```

## Best Practices

1. **One edge case per file** - Keep test cases focused
2. **Descriptive names** - Use clear, specific filenames
3. **Minimal examples** - Small SVGs that isolate the edge case
4. **Document thoroughly** - Explain what makes it special
5. **Verify manually first** - Always check results before adding to suite
6. **Update test suite** - Add to `test_extraction.py` immediately

## Running Specific Tests

To run only specific tests, modify `test_extraction.py` temporarily:

```python
def main():
    tester = ExtractionTester()

    # Comment out tests you don't want to run
    # tester.add_test_case(create_baseline_test_case())

    # Run only your test
    tester.add_test_case(your_test_case)

    tester.run_all_tests()
```

## Continuous Integration

As the test suite grows, consider:
- Running tests automatically on every change
- Setting up CI/CD pipeline
- Generating coverage reports
- Tracking test execution time

## Contact

If you encounter a diagram that breaks the extractor, please:
1. Save the SVG to this directory
2. Document the issue
3. Create a test case
4. Fix the extraction logic
5. Verify all tests still pass
