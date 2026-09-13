#!/usr/bin/env python3
"""
Test script for triple-source merge: API + Scraper + What's New
Tests the complete integrated system after adding What's New detector
"""

import sys
import logging
from pathlib import Path

# Add the scraper to path
scraper_path = Path(__file__).parent.absolute()
sys.path.insert(0, str(scraper_path))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_whats_new_detector():
    """Test What's New detector module"""
    print("\n" + "="*70)
    print("TEST 1: What's New Detector")
    print("="*70)
    
    try:
        from bis_change_detector.whats_new_detector import WhatsNewDetector
        
        logger.info("Initializing What's New detector...")
        detector = WhatsNewDetector()
        
        # Test fetching main page
        logger.info("Fetching main What's New page (main page only)...")
        main_entries = detector.get_main_page_entries()
        
        print(f"\n✓ Main page fetched: {len(main_entries)} entries found")
        
        if main_entries:
            print("\n  Sample entries:")
            for entry in main_entries[:3]:
                print(f"    - {entry.standard_id or 'Unknown'}: {entry.title[:50]}...")
        
        # Test standard extraction
        logger.info("Extracting standards from entries...")
        standards = detector.get_standards_from_whats_new(include_archive=False)
        
        print(f"\n✓ Standards extracted: {len(standards)} unique standards found")
        
        if standards:
            print("\n  Top standards mentioned:")
            for std_id, info in sorted(standards.items(), 
                                       key=lambda x: x[1]['count'], 
                                       reverse=True)[:10]:
                print(f"    - {std_id}: {info['count']} mentions (Latest: {info['latest_date']})")
        
        print("\n✓ TEST 1 PASSED: What's New Detector working correctly")
        return True
    
    except Exception as e:
        print(f"\n✗ TEST 1 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_config_with_whats_new():
    """Test configuration loading with What's New options"""
    print("\n" + "="*70)
    print("TEST 2: Configuration with What's New Options")
    print("="*70)
    
    try:
        from bis_change_detector.config import Settings
        
        logger.info("Loading configuration...")
        config = Settings.from_env()
        
        print(f"\n✓ Configuration loaded successfully")
        print(f"  - API Enabled: {config.api_enabled}")
        print(f"  - Scraper Enabled: {config.scraper_enabled}")
        print(f"  - What's New Enabled: {config.whats_new_enabled}")
        print(f"  - What's New Include Archive: {config.whats_new_include_archive}")
        print(f"  - What's New Max Pages: {config.whats_new_max_pages}")
        print(f"  - Redact PII: {config.redact_pii}")
        
        # Verify What's New config
        assert hasattr(config, 'whats_new_enabled'), "Missing whats_new_enabled"
        assert hasattr(config, 'whats_new_include_archive'), "Missing whats_new_include_archive"
        assert hasattr(config, 'whats_new_max_pages'), "Missing whats_new_max_pages"
        assert config.whats_new_enabled == True, "What's New should be enabled by default"
        assert config.whats_new_max_pages <= 10, "Max pages should not exceed 10"
        
        print("\n✓ TEST 2 PASSED: Configuration includes all What's New options")
        return True
    
    except Exception as e:
        print(f"\n✗ TEST 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_change_detector_integration():
    """Test that change_detector.py imports and uses What's New detector"""
    print("\n" + "="*70)
    print("TEST 3: Change Detector Integration")
    print("="*70)
    
    try:
        from bis_change_detector.change_detector import ChangeDetector
        from bis_change_detector.config import Settings
        
        logger.info("Loading configuration...")
        config = Settings.from_env()
        
        logger.info("Initializing ChangeDetector...")
        detector = ChangeDetector(config)
        
        # Check that the detector has the new method
        assert hasattr(detector, '_fetch_whats_new_standards'), "Missing _fetch_whats_new_standards method"
        
        print(f"\n✓ ChangeDetector initialized successfully")
        print(f"  - Has _fetch_whats_new_standards method: Yes")
        print(f"  - What's New enabled in config: {config.whats_new_enabled}")
        
        # Test the method (with What's New disabled to avoid network calls in basic test)
        logger.info("Testing _fetch_whats_new_standards method...")
        standards = detector._fetch_whats_new_standards()
        
        print(f"  - Fetch returned: {len(standards)} standards")
        print(f"  - Type: {type(standards)}")
        
        print("\n✓ TEST 3 PASSED: Change Detector properly integrated")
        return True
    
    except Exception as e:
        print(f"\n✗ TEST 3 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_pii_redaction_still_works():
    """Verify PII redaction still works after changes"""
    print("\n" + "="*70)
    print("TEST 4: PII Redaction (Backward Compatibility)")
    print("="*70)
    
    try:
        from bis_change_detector.artifact_parser import redact
        
        test_cases = [
            ("Email: john@example.com", "john@example.com"),
            ("Phone: +91-9876543210", "+91-9876543210"),
            ("Contact: test@company.co.in and +91-8765432100", "test@company.co.in"),
        ]
        
        print(f"\n Testing PII redaction...")
        for text, sensitive_data in test_cases:
            result = redact(text)
            assert sensitive_data not in result, f"PII not redacted in: {result}"
            assert "[redacted_" in result, f"No redaction marker in: {result}"
            print(f"  ✓ {text[:40]}... → Redacted")
        
        print("\n✓ TEST 4 PASSED: PII redaction working correctly")
        return True
    
    except Exception as e:
        print(f"\n✗ TEST 4 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_smart_headers_still_works():
    """Verify smart header detection still works after changes"""
    print("\n" + "="*70)
    print("TEST 5: Smart Header Detection (Backward Compatibility)")
    print("="*70)
    
    try:
        from bis_change_detector.artifact_parser import find_header_row
        
        # Simulate BIS Excel export with letterhead
        test_data = [
            ['Bureau of Indian Standards', '', '', ''],           # Row 0 (letterhead)
            ['', '', '', ''],                                      # Row 1 (blank)
            ['The National Standards Body of India', '', '', ''], # Row 2 (letterhead)
            ['', '', '', ''],                                      # Row 3 (blank)
            ['IS Number', 'Title', 'Status', 'Year'],             # Row 4 (REAL HEADER)
            ['12345', 'Test Standard', 'Active', '2020'],         # Row 5 (data)
        ]
        
        logger.info("Testing header detection...")
        header_idx = find_header_row(test_data)
        
        assert header_idx == 4, f"Expected header at row 4, found at {header_idx}"
        
        print(f"\n✓ Header detected at row: {header_idx} (expected 4)")
        print(f"  - Correctly skipped letterhead rows 0-2")
        print(f"  - Identified real header: {test_data[header_idx]}")
        
        print("\n✓ TEST 5 PASSED: Smart header detection working correctly")
        return True
    
    except Exception as e:
        print(f"\n✗ TEST 5 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("TRIPLE-SOURCE MERGE TEST SUITE")
    print("(API + Scraper + What's New)")
    print("="*70)
    
    results = {
        "What's New Detector": test_whats_new_detector(),
        "Configuration": test_config_with_whats_new(),
        "ChangeDetector Integration": test_change_detector_integration(),
        "PII Redaction (Backward Compat)": test_pii_redaction_still_works(),
        "Smart Headers (Backward Compat)": test_smart_headers_still_works(),
    }
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        symbol = "✓" if passed else "✗"
        print(f"{symbol} {test_name}: {status}")
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n" + "="*70)
        print("ALL TESTS PASSED - TRIPLE-SOURCE SYSTEM WORKING")
        print("="*70)
        return 0
    else:
        print("\n" + "="*70)
        print("SOME TESTS FAILED - PLEASE REVIEW")
        print("="*70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
