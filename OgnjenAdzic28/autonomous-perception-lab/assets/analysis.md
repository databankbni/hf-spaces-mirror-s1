# KITTI Tracking Real Run Analysis

- Run: `data/artifacts/runs/kitti_tracking_yolo`
- Dataset: `kitti-tracking`
- Frames: 12
- Detections: 43
- Tracks: 8
- Estimated ID switches: n/a
- Mean valid sparse-depth pixels: 4.38%

## Real Data Evidence

- frames: `data/raw/kitti_tracking_sample/training/image_02/0000/*.png`
- calibration: `data/raw/kitti_tracking_sample/training/calib/0000.txt`
- labels: `data/raw/kitti_tracking_sample/training/label_02/0000.txt`
- velodyne: `data/raw/kitti_tracking_sample/training/velodyne/0000/*.bin`
- detector: `ultralytics-yolo11n-coco`
- depth: `kitti-velodyne-sparse-depth`
- source: `KITTI Vision Benchmark Suite on AWS Open Data`

## Class Counts

- car: 10
- cyclist: 23
- pedestrian: 6
- traffic_light: 4

## Detection Quality At IoU 0.50

- ground truth: 37
- true positives: 24
- false positives: 15
- false negatives: 13
- ignored out-of-scope predictions: 4
- precision: 0.615
- recall: 0.649
- F1: 0.632
- mean matched IoU: 0.697

## Distance Summary

- min: 5.96 m
- mean: 11.06 m
- max: 16.71 m

## Track Lengths

- track 1: 12 frames
- track 2: 5 frames
- track 3: 10 frames
- track 4: 2 frames
- track 5: 9 frames
- track 6: 2 frames
- track 7: 1 frames
- track 8: 2 frames

## Still Approximate

- Detector is a COCO-pretrained YOLO model evaluated on KITTI labels without fine-tuning.
- Sparse depth is real projected Velodyne LiDAR, not dense monocular depth.
- BEV projection uses a simple bottom-center image point and camera intrinsics.
- Tracker IDs are produced by the project tracker and are not forced to KITTI track IDs.
