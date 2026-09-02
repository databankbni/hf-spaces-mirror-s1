import spaces
import torch
print(f'torch version:{torch.__version__}')
import functools
import gc
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
import uuid

import cv2
import gradio as gr

from huggingface_hub import hf_hub_download
from PIL import Image

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.misc.image_io import save_interpolated_video
from src.model.model.anysplat import AnySplat
from src.model.ply_export import export_ply
from src.utils.image import process_image

os.environ["ANYSPLAT_PROCESSED"] = f"{os.getcwd()}/proprocess_results"

from plyfile import PlyData
import numpy as np
import argparse
from io import BytesIO


def extract_file_path(item):
    path = None
    if item is None:
        return None
    elif isinstance(item, str):
        path = item
    elif isinstance(item, tuple):
        path = extract_file_path(item[0])
    elif isinstance(item, dict):
        if "path" in item and item["path"]:
            path = item["path"]
        elif "name" in item and item["name"]:
            path = item["name"]
        elif "image" in item:
            path = extract_file_path(item["image"])
        elif "video" in item:
            path = extract_file_path(item["video"])
        elif "url" in item and item["url"]:
            path = item["url"]
        else:
            path = str(item)
    else:
        path = str(item)

    if path and not os.path.isabs(path):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        cand = os.path.join(base_dir, path)
        if os.path.exists(cand):
            return cand

    return path



def process_ply_to_splat(ply_file_path):
    plydata = PlyData.read(ply_file_path)
    vert = plydata["vertex"]
    sorted_indices = np.argsort(
        -np.exp(vert["scale_0"] + vert["scale_1"] + vert["scale_2"])
        / (1 + np.exp(-vert["opacity"]))
    )
    buffer = BytesIO()
    for idx in sorted_indices:
        v = plydata["vertex"][idx]
        position = np.array([v["x"], v["y"], v["z"]], dtype=np.float32)
        scales = np.exp(
            np.array(
                [v["scale_0"], v["scale_1"], v["scale_2"]],
                dtype=np.float32,
            )
        )
        rot = np.array(
            [v["rot_0"], v["rot_1"], v["rot_2"], v["rot_3"]],
            dtype=np.float32,
        )
        SH_C0 = 0.28209479177387814
        color = np.array(
            [
                0.5 + SH_C0 * v["f_dc_0"],
                0.5 + SH_C0 * v["f_dc_1"],
                0.5 + SH_C0 * v["f_dc_2"],
                1 / (1 + np.exp(-v["opacity"])),
            ]
        )
        buffer.write(position.tobytes())
        buffer.write(scales.tobytes())
        buffer.write((color * 255).clip(0, 255).astype(np.uint8).tobytes())
        buffer.write(
            ((rot / np.linalg.norm(rot)) * 128 + 128)
            .clip(0, 255)
            .astype(np.uint8)
            .tobytes()
        )

    return buffer.getvalue()

def save_splat_file(splat_data, output_path):
    with open(output_path, "wb") as f:
        f.write(splat_data)

def get_reconstructed_scene(outdir, image_files, model, device):

    images = [process_image(img_path) for img_path in image_files]
    images = torch.stack(images, dim=0).unsqueeze(0).to(device)  # [1, K, 3, 448, 448]
    b, v, c, h, w = images.shape

    assert c == 3, "Images must have 3 channels"

    gaussians, pred_context_pose = model.inference((images + 1) * 0.5)

    pred_all_extrinsic = pred_context_pose["extrinsic"]
    pred_all_intrinsic = pred_context_pose["intrinsic"]
    video, depth_colored = save_interpolated_video(
        pred_all_extrinsic,
        pred_all_intrinsic,
        b,
        h,
        w,
        gaussians,
        outdir,
        model.decoder,
    )
    plyfile = os.path.join(outdir, "gaussians.ply")
    # splatfile = os.path.join(outdir, "gaussians.splat")

    export_ply(
        gaussians.means[0],
        gaussians.scales[0],
        gaussians.rotations[0],
        gaussians.harmonics[0],
        gaussians.opacities[0],
        Path(plyfile),
        save_sh_dc_only=True,
    )
    # splat_data = process_ply_to_splat(plyfile)
    # save_splat_file(splat_data, splatfile)

    # Clean up
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return plyfile, video, depth_colored

def extract_images(input_images, session_id):
    start_time = time.time()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    if session_id is None:
        session_id = uuid.uuid4().hex

    base_dir = os.path.join(os.environ["ANYSPLAT_PROCESSED"], session_id)
    target_dir = base_dir
    target_dir_images = os.path.join(target_dir, "images")

    if os.path.exists(target_dir):
        shutil.rmtree(target_dir, ignore_errors=True)
        
    os.makedirs(target_dir, exist_ok=True)
    os.makedirs(target_dir_images, exist_ok=True)

    image_paths = []

    if input_images is not None:
        for file_data in input_images:
            file_path = extract_file_path(file_data)
            if file_path and os.path.exists(file_path):
                dst_path = os.path.join(target_dir_images, os.path.basename(file_path))
                shutil.copy(file_path, dst_path)
                image_paths.append(dst_path)

    end_time = time.time()
    print(
        f"Files copied to {target_dir_images}; took {end_time - start_time:.3f} seconds"
    )
    return target_dir, image_paths
    

def extract_frames(input_video, session_id):
    start_time = time.time()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    if session_id is None:
        session_id = uuid.uuid4().hex

    base_dir = os.path.join(os.environ["ANYSPLAT_PROCESSED"], session_id)
    target_dir = base_dir
    target_dir_images = os.path.join(target_dir, "images")

    if os.path.exists(target_dir):
        shutil.rmtree(target_dir, ignore_errors=True)
        
    os.makedirs(target_dir, exist_ok=True)
    os.makedirs(target_dir_images, exist_ok=True)

    image_paths = []

    if input_video is not None:
        video_path = extract_file_path(input_video)
        if video_path and os.path.exists(video_path):
            vs = cv2.VideoCapture(video_path)
            fps = vs.get(cv2.CAP_PROP_FPS)
            total_frames = int(vs.get(cv2.CAP_PROP_FRAME_COUNT)) if vs.isOpened() else 0
            if not fps or fps <= 0:
                fps = 30
            if total_frames > 0:
                frame_interval = max(1, total_frames // 14)
            else:
                frame_interval = max(1, int(fps * 0.5))

            count = 0
            video_frame_num = 0
            while True:
                gotit, frame = vs.read()
                if not gotit:
                    break
                count += 1
                if count == 1 or count % frame_interval == 0:
                    image_path = os.path.join(
                        target_dir_images, f"{video_frame_num:06}.png"
                    )
                    cv2.imwrite(image_path, frame)
                    image_paths.append(image_path)
                    video_frame_num += 1

    # Sort final images for gallery
    image_paths = sorted(image_paths)

    end_time = time.time()
    print(
        f"Files copied to {target_dir_images}; took {end_time - start_time:.3f} seconds"
    )
    return target_dir, image_paths


def update_gallery_on_video_upload(input_video, session_id):
    if not input_video:
        return None, None, None
        
    target_dir, image_paths = extract_frames(input_video, session_id)
    return None, target_dir, image_paths

def update_gallery_on_images_upload(input_images, session_id):

    if not input_images:
        return None, None, None
        
    target_dir, image_paths = extract_images(input_images, session_id)
    return None, target_dir, image_paths

MODEL = None

def get_model():
    global MODEL
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if MODEL is None:
        print(f"Loading AnySplat model onto {device}...")
        MODEL = AnySplat.from_pretrained("lhjiang/anysplat")
        MODEL = MODEL.to(device)
        MODEL.eval()
        for param in MODEL.parameters():
            param.requires_grad = False
    else:
        MODEL = MODEL.to(device)
    return MODEL, device

def _do_generate_splats_from_images(image_paths, session_id=None):
    model, device = get_model()

    processed_image_paths = []
    if image_paths:
        for file_data in image_paths:
            path = extract_file_path(file_data)
            if path and os.path.exists(path):
                processed_image_paths.append(path)

    image_paths = processed_image_paths
    print("Processed image paths:", image_paths)

    if not image_paths:
        raise gr.Error("No valid image files provided.")

    if len(image_paths) == 1:
        image_paths.append(image_paths[0])

    if session_id is None:
        session_id = uuid.uuid4().hex
    
    start_time = time.time()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    base_dir = os.path.join(os.environ["ANYSPLAT_PROCESSED"], session_id)

    print("Running run_model...")
    with torch.no_grad():
        plyfile, rgb_vid, depth_vid = get_reconstructed_scene(base_dir, image_paths, model, device)

    end_time = time.time()
    print(f"Total time: {end_time - start_time:.2f} seconds (including IO)")

    return plyfile, rgb_vid, depth_vid

@spaces.GPU(duration=120)
def generate_splats_from_video(video_path, session_id=None):
    video_path = extract_file_path(video_path)
    if session_id is None:
        session_id = uuid.uuid4().hex

    images_folder, image_paths = extract_frames(video_path, session_id)
    plyfile, rgb_vid, depth_vid = _do_generate_splats_from_images(image_paths, session_id)

    formatted_gallery = [(p, None) for p in image_paths] if image_paths else []
    return plyfile, rgb_vid, depth_vid, formatted_gallery

@spaces.GPU(duration=120)
def generate_splats_from_images(image_paths, session_id=None):
    return _do_generate_splats_from_images(image_paths, session_id)

def cleanup(request: gr.Request):
    sid = request.session_hash
    if sid:
        d1 = os.path.join(os.environ["ANYSPLAT_PROCESSED"], sid)
        shutil.rmtree(d1, ignore_errors=True)
        
def start_session(request: gr.Request):
    return request.session_hash

if __name__ == "__main__":
    css = """
        #col-container {
            margin: 0 auto;
            max-width: 1024px;
        }
        """
    with gr.Blocks(css=css, title="AnySplat Demo") as demo:
        session_state = gr.State()
        demo.load(start_session, outputs=[session_state])
                
        target_dir_output = gr.Textbox(label="Target Dir", visible=False, value="None")
        is_example = gr.Textbox(label="is_example", visible=False, value="None")
        num_images = gr.Textbox(label="num_images", visible=False, value="None")
        dataset_name = gr.Textbox(label="dataset_name", visible=False, value="None")
        scene_name = gr.Textbox(label="scene_name", visible=False, value="None")
        image_type = gr.Textbox(label="image_type", visible=False, value="None")

        with gr.Column(elem_id="col-container"):

            gr.HTML(
                """
                <div style="text-align: center;">
                    <p style="font-size:16px; display: inline; margin: 0;">
                        <strong>AnySplat</strong> – Feed-forward 3D Gaussian Splatting from Unconstrained Views
                    </p>
                    <a href="https://github.com/OpenRobotLab/AnySplat" style="display: inline-block; vertical-align: middle; margin-left: 0.5em;">
                        <img src="https://img.shields.io/badge/GitHub-Repo-blue" alt="GitHub Repo">
                    </a>
                </div>
                <div style="text-align: center;">
                    <strong>HF Space by:</strong>
                    <a href="https://twitter.com/alexandernasa/" style="display: inline-block; vertical-align: middle; margin-left: 0.5em;">
                        <img src="https://img.shields.io/twitter/url/https/twitter.com/cloudposse.svg?style=social&label=Follow Me" alt="GitHub Repo">
                    </a>
                </div>
                """
            )
        
            with gr.Row():
                with gr.Column():

                    with gr.Tab("Video"):
                        input_video = gr.File(label="Upload Video", file_types=["video"], height=512)
                    with gr.Tab("Images"):
                        input_images = gr.File(file_count="multiple", label="Upload Files", height=512)
                        
                    submit_btn = gr.Button(
                        "🖌️ Generate Gaussian Splat", scale=1, variant="primary"
                    )
        
                    image_gallery = gr.Gallery(
                        label="Preview",
                        columns=4,
                        height="300px",
                        show_download_button=True,
                        object_fit="contain",
                        preview=True,
                    )
    
                with gr.Column():
                    with gr.Column():
                        gr.HTML(
                            """
                            <p style="opacity: 0.6; font-style: italic;">
                              This might take a few seconds to load the 3D model
                            </p>
                            """
                        )
                        reconstruction_output = gr.Model3D(
                            label="Ply Gaussian Model",
                            height=512,
                            zoom_speed=0.5,
                            pan_speed=0.5,
                            # camera_position=[20, 20, 20],
                        )
                
                    with gr.Row():
                        rgb_video = gr.Video(
                            label="RGB Video", interactive=False, autoplay=True
                        )
                        depth_video = gr.Video(
                            label="Depth Video",
                            interactive=False,
                            autoplay=True,
                        )
                    with gr.Row():
                        examples = [
                            ["examples/video/re10k_1eca36ec55b88fe4.mp4"],
                            ["examples/video/spann3r.mp4"],
                            ["examples/video/bungeenerf_colosseum.mp4"],
                            ["examples/video/fox.mp4"],
                            ["examples/video/vrnerf_apartment.mp4"],
                            # [None, "examples/video/vrnerf_kitchen.mp4", "vrnerf", "kitchen", "17", "Real", "True",],
                            # [None, "examples/video/vrnerf_riverview.mp4", "vrnerf", "riverview", "12", "Real", "True",],
                            # [None, "examples/video/vrnerf_workshop.mp4", "vrnerf", "workshop", "32", "Real", "True",],
                            # [None, "examples/video/fillerbuster_ramen.mp4", "fillerbuster", "ramen", "32", "Real", "True",],
                            # [None, "examples/video/meganerf_rubble.mp4", "meganerf", "rubble", "10", "Real", "True",],
                            # [None, "examples/video/llff_horns.mp4", "llff", "horns", "12", "Real", "True",],
                            # [None, "examples/video/llff_fortress.mp4", "llff", "fortress", "7", "Real", "True",],
                            # [None, "examples/video/dtu_scan_106.mp4", "dtu", "scan_106", "20", "Real", "True",],
                            # [None, "examples/video/horizongs_hillside_summer.mp4", "horizongs", "hillside_summer", "55", "Synthetic", "True",],
                            # [None, "examples/video/kitti360.mp4", "kitti360", "kitti360", "64", "Real", "True",],
                        ]
                
                        gr.Examples(
                            examples=examples,
                            inputs=[
                                input_video
                            ],
                            outputs=[
                                reconstruction_output,
                                rgb_video,
                                depth_video,
                                image_gallery
                            ],
                            fn=generate_splats_from_video,
                            cache_examples=False,
                        )
                            
               
        submit_btn.click(
            fn=generate_splats_from_images,
            inputs=[input_images, session_state],
            outputs=[reconstruction_output, rgb_video, depth_video],
            api_name="generate_splats_from_images"
        )

        submit_video_btn = gr.Button(
            "🖌️ Generate Gaussian Splat from Video", scale=1, variant="primary"
        )
        submit_video_btn.click(
            fn=generate_splats_from_video,
            inputs=[input_video, session_state],
            outputs=[reconstruction_output, rgb_video, depth_video, image_gallery],
            api_name="generate_splats_from_video"
        )

        input_video.upload(
            fn=update_gallery_on_video_upload,
            inputs=[input_video, session_state],
            outputs=[reconstruction_output, target_dir_output, image_gallery],
            show_api=False
        )

        input_images.upload(
            fn=update_gallery_on_images_upload,
            inputs=[input_images, session_state],
            outputs=[reconstruction_output, target_dir_output, image_gallery],
            show_api=False
        )

        app_dir = os.path.dirname(os.path.abspath(__file__))
        examples_dir = os.path.join(app_dir, "examples")
        results_dir = os.path.join(app_dir, "proprocess_results")
        try:
            gr.set_static_paths(paths=[app_dir, examples_dir, results_dir, "/tmp"])
        except Exception as e:
            print("set_static_paths warning:", e)

        demo.unload(cleanup)
        demo.queue()
        demo.launch(
            show_error=True,
            ssr_mode=False,
            allowed_paths=[
                app_dir,
                examples_dir,
                results_dir,
                "/tmp"
            ]
        )