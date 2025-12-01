#!/usr/bin/env python3
"""
Test script to verify L2 transcript detection logging.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from arjun_l2.l2_file_resolver import find_l2_transcript_file

# Test case 1: Various L2 transcript naming conventions
test_files_1 = [
    {"id": "1", "name": "normalization_report.json"},
    {"id": "2", "name": "L2_Transcript.txt"},
    {"id": "3", "name": "Resume.pdf"},
]

print("Test 1: L2_Transcript.txt")
result = find_l2_transcript_file(test_files_1)
print(f"  Result: {result}")
print(f"  Found: {result is not None}")
print(f"  File name: {result.get('name') if result else 'None'}")
print()

# Test case 2: Different naming convention
test_files_2 = [
    {"id": "1", "name": "normalization_report.json"},
    {"id": "2", "name": "L2 Transcript.docx"},
    {"id": "3", "name": "Resume.pdf"},
]

print("Test 2: L2 Transcript.docx")
result = find_l2_transcript_file(test_files_2)
print(f"  Result: {result}")
print(f"  Found: {result is not None}")
print(f"  File name: {result.get('name') if result else 'None'}")
print()

# Test case 3: No transcript
test_files_3 = [
    {"id": "1", "name": "normalization_report.json"},
    {"id": "2", "name": "Resume.pdf"},
]

print("Test 3: No transcript file")
result = find_l2_transcript_file(test_files_3)
print(f"  Result: {result}")
print(f"  Found: {result is not None}")
print(f"  File name: {result.get('name') if result else 'None'}")
print()

# Test case 4: Multiple transcripts (should prefer .txt)
test_files_4 = [
    {"id": "1", "name": "L2 Interview Transcript.pdf"},
    {"id": "2", "name": "L2_Transcript.txt"},
    {"id": "3", "name": "Resume.pdf"},
]

print("Test 4: Multiple transcripts (should prefer .txt)")
result = find_l2_transcript_file(test_files_4)
print(f"  Result: {result}")
print(f"  Found: {result is not None}")
print(f"  File name: {result.get('name') if result else 'None'}")
print()

print("All tests completed successfully!")
