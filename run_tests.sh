#!/bin/bash
# Test runner script for Hithonix Recruitment Automation

echo "==================================="
echo "Hithonix Recruitment Automation"
echo "Test Suite Runner"
echo "==================================="
echo ""

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo "⚠️  pytest not found. Installing test dependencies..."
    pip install -r requirements-test.txt
    echo ""
fi

# Run tests based on argument
case "$1" in
    "all")
        echo "🧪 Running all tests..."
        pytest tests/ -v
        ;;
    "coverage")
        echo "🧪 Running tests with coverage..."
        pytest tests/ --cov=. --cov-report=html --cov-report=term
        echo ""
        echo "📊 Coverage report generated in htmlcov/index.html"
        ;;
    "batch")
        echo "🧪 Running RivaL1BatchProcessor tests..."
        pytest tests/test_riva_l1_batch.py -v
        ;;
    "normalizer")
        echo "🧪 Running Normalizer tests..."
        pytest tests/test_normalizer.py -v
        ;;
    "quick")
        echo "🧪 Running quick smoke tests..."
        pytest tests/ -v -k "test_classify" --maxfail=3
        ;;
    *)
        echo "Usage: ./run_tests.sh [all|coverage|batch|normalizer|quick]"
        echo ""
        echo "Options:"
        echo "  all        - Run all tests"
        echo "  coverage   - Run tests with coverage report"
        echo "  batch      - Run RivaL1BatchProcessor tests only"
        echo "  normalizer - Run Normalizer tests only"
        echo "  quick      - Run quick classification tests"
        echo ""
        echo "Example: ./run_tests.sh all"
        exit 1
        ;;
esac
