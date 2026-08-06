#!/bin/bash
set -e

# Install ffmpeg for video generation support
apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
