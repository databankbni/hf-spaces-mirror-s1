#!/bin/bash
# Quick test script for ring-sizer
# Usage:
#   ./script/test.sh              - Run basic test with debug output
#   ./script/test.sh [image]      - Test with specific image
#   ./script/test.sh --no-debug   - Run without debug visualization

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory and project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

# Change to project root
cd "$PROJECT_ROOT"

# Python executable
PYTHON=".venv/bin/python"

# Check if virtual environment exists
if [ ! -f "$PYTHON" ]; then
    echo -e "${YELLOW}Virtual environment not found. Creating...${NC}"
    python3 -m venv .venv
    echo -e "${GREEN}Installing dependencies...${NC}"
    .venv/bin/pip install -r requirements.txt
fi

# Default values
INPUT_IMAGE=""
OUTPUT_JSON="output/test_result.json"
ENABLE_DEBUG=true
SKIP_CARD=false
FINGER_INDEX="index"

# Parse arguments
while [ $# -gt 0 ]; do
    case "$1" in
        --no-debug)
            ENABLE_DEBUG=false
            shift
            ;;
        --skip-card-detection|--skip-card)
            SKIP_CARD=true
            shift
            ;;
        --finger-index|--finger|-f)
            if [ -z "$2" ]; then
                echo -e "${YELLOW}Error: --finger-index requires a value: auto|index|middle|ring|pinky${NC}"
                exit 1
            fi
            case "$2" in
                auto|index|middle|ring|pinky)
                    FINGER_INDEX="$2"
                    ;;
                *)
                    echo -e "${YELLOW}Error: Invalid finger index '$2'. Use: auto|index|middle|ring|pinky${NC}"
                    exit 1
                    ;;
            esac
            shift 2
            ;;
        --help|-h)
            echo "Usage: ./script/test.sh [OPTIONS] [IMAGE]"
            echo ""
            echo "Options:"
            echo "  --no-debug              Run without debug visualization"
            echo "  --skip-card-detection   Skip card detection (testing mode for finger segmentation)"
            echo "  --finger-index, -f      Finger to measure: auto|index|middle|ring|pinky (default: index)"
            echo "  --help, -h              Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./script/test.sh                        # Use first available test image"
            echo "  ./script/test.sh input/my_image.jpg     # Test with specific image"
            echo "  ./script/test.sh --no-debug             # Skip debug output"
            echo "  ./script/test.sh --skip-card-detection  # Test finger segmentation without card"
            echo "  ./script/test.sh -f ring                # Measure ring finger"
            exit 0
            ;;
        *)
            INPUT_IMAGE="$1"
            shift
            ;;
    esac
done

# Find first available test image if not specified
if [ -z "$INPUT_IMAGE" ]; then
    echo -e "${BLUE}Looking for test images in input/...${NC}"

    # Try to find any image file
    for ext in jpg jpeg png heic; do
        INPUT_IMAGE=$(find input/ -maxdepth 1 -type f -iname "*.$ext" | head -1)
        if [ -n "$INPUT_IMAGE" ]; then
            break
        fi
    done

    if [ -z "$INPUT_IMAGE" ]; then
        echo -e "${YELLOW}No test images found in input/ directory${NC}"
        echo "Please add a test image to input/ or specify one as an argument:"
        echo "  ./script/test.sh path/to/image.jpg"
        exit 1
    fi
fi

# Check if input file exists
if [ ! -f "$INPUT_IMAGE" ]; then
    echo -e "${YELLOW}Error: Input file not found: $INPUT_IMAGE${NC}"
    exit 1
fi

# Create output directory if it doesn't exist
mkdir -p output
rm -rf output/*_debug/*

# Build command
#CMD="$PYTHON measure_finger.py --input $INPUT_IMAGE --output $OUTPUT_JSON --edge-method sobel --edge-detection-method canny_contour"
CMD="$PYTHON measure_finger.py --input $INPUT_IMAGE --output $OUTPUT_JSON --finger-index $FINGER_INDEX"

if [ "$ENABLE_DEBUG" = true ]; then
    CMD="$CMD --debug"
fi

if [ "$SKIP_CARD" = true ]; then
    CMD="$CMD --skip-card-detection"
fi

# Print test info
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Ring Sizer Quick Test${NC}"
echo -e "${GREEN}========================================${NC}"
echo -e "${BLUE}Input:${NC}  $INPUT_IMAGE"
echo -e "${BLUE}Output:${NC} $OUTPUT_JSON"
echo -e "${BLUE}Finger:${NC} $FINGER_INDEX"
RESULT_PNG="${OUTPUT_JSON%.json}.png"
if [ "$ENABLE_DEBUG" = true ]; then
    echo -e "${BLUE}Debug:${NC}  enabled"
fi
if [ "$SKIP_CARD" = true ]; then
    echo -e "${YELLOW}Mode:${NC}   TESTING (card detection skipped)"
fi
echo -e "${GREEN}========================================${NC}"
echo ""

# Run the measurement
$CMD

# Print results
echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Test Complete!${NC}"
echo -e "${GREEN}========================================${NC}"

if [ -f "$OUTPUT_JSON" ]; then
    echo -e "${BLUE}Results:${NC}"
    cat "$OUTPUT_JSON" | python3 -m json.tool
    echo ""
fi

if [ -f "$RESULT_PNG" ]; then
    echo -e "${BLUE}Result image saved to:${NC} $RESULT_PNG"
    echo ""
fi

echo -e "${GREEN}========================================${NC}"
