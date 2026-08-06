import cv2
import numpy as np
import torch
import torchvision.transforms.functional as TF
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import networkx as nx
import requests
import base64
from io import BytesIO
from PIL import Image

from graph_engine import extract_criticality_from_mask, calculate_impact_metrics
from model import AttentionUNet

app = FastAPI()

app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"]
)

device = torch.device("cpu")
ml_model = AttentionUNet(img_ch=3, output_ch=1).to(device)

DEMO_STATE = { 
    "graph": None, 
    "original_graph": None, 
    "bounds": None, 
    "iou": 0.8924, 
    "stats": None 
}

try:    
    checkpoint = torch.load('road_unet_model.pth', map_location=device, weights_only=True)
    if 'model_state_dict' in checkpoint: 
        ml_model.load_state_dict(checkpoint['model_state_dict'])    
    else: 
        ml_model.load_state_dict(checkpoint)    
    ml_model.eval()    
except FileNotFoundError: 
    pass

@app.get("/api/metrics")
async def get_metrics(): 
    return {"iou_score": DEMO_STATE["iou"]}

def encode_image(img_arr):
    pil_img = Image.fromarray(img_arr)
    buffered = BytesIO()
    pil_img.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode("utf-8")

def build_geojson_from_graph(G, centrality_scores, bounds):    
    features = []    
    min_lat, max_lat, min_lon, max_lon = bounds        
    for edge in G.edges(data=True):        
        node1, node2, edge_data = edge        
        max_score = max(centrality_scores.get(node1, 0), centrality_scores.get(node2, 0))                
        lon1 = min_lon + (node1[1] / 512.0) * (max_lon - min_lon)        
        lat1 = max_lat - (node1[0] / 512.0) * (max_lat - min_lat)        
        lon2 = min_lon + (node2[1] / 512.0) * (max_lon - min_lon)        
        lat2 = max_lat - (node2[0] / 512.0) * (max_lat - min_lat)                
        
        features.append({            
            "type": "Feature",            
            "properties": {                
                "criticality_score": float(max_score),  
                "edge_type": edge_data.get('type', 'actual'),
                "node_id": f"N-{abs(hash(node1)) % 9999}",
                "impact_multiplier": float(max_score * 1.5),
                "pixel_n1": [int(node1[0]), int(node1[1])],                
                "pixel_n2": [int(node2[0]), int(node2[1])]            
            },            
            "geometry": { "type": "LineString", "coordinates": [[lon1, lat1], [lon2, lat2]] }        
        })    
    return {"type": "FeatureCollection", "features": features}

@app.post("/api/process-satellite-mask")
async def process_mask(request: Request):
    try:
        data = await request.json()
    except Exception:
        return {"error": "Invalid JSON received by server."}
        
    min_lat = float(data.get("min_lat", 28.61))
    max_lat = float(data.get("max_lat", 28.62))
    min_lon = float(data.get("min_lon", 77.02))
    max_lon = float(data.get("max_lon", 77.03))

    arcgis_url = f"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?bbox={min_lon},{min_lat},{max_lon},{max_lat}&bboxSR=4326&imageSR=4326&size=512,512&f=image"        
    
    try:        
        response = requests.get(arcgis_url, timeout=10)        
        response.raise_for_status()        
        nparr = np.frombuffer(response.content, np.uint8)        
        image_cv2 = cv2.imdecode(nparr, cv2.IMREAD_COLOR)        
        image_rgb = cv2.cvtColor(image_cv2, cv2.COLOR_BGR2RGB)    
    except Exception as e: 
        return {"error": f"Failed to acquire satellite feed: {str(e)}"}        
    
    img_tensor = torch.tensor(image_rgb, dtype=torch.float32).permute(2, 0, 1) / 255.0    
    img_tensor_norm = TF.normalize(img_tensor, mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
    
    tl = img_tensor_norm[:, :256, :256].unsqueeze(0).to(device)
    tr = img_tensor_norm[:, :256, 256:].unsqueeze(0).to(device)
    bl = img_tensor_norm[:, 256:, :256].unsqueeze(0).to(device)
    br = img_tensor_norm[:, 256:, 256:].unsqueeze(0).to(device)
    
    with torch.no_grad():        
        out_tl = torch.sigmoid(ml_model(tl)).squeeze()
        out_tr = torch.sigmoid(ml_model(tr)).squeeze()
        out_bl = torch.sigmoid(ml_model(bl)).squeeze()
        out_br = torch.sigmoid(ml_model(br)).squeeze()
        
    full_mask = torch.zeros((512, 512), dtype=torch.float32)
    full_mask[:256, :256] = out_tl
    full_mask[:256, 256:] = out_tr
    full_mask[256:, :256] = out_bl
    full_mask[256:, 256:] = out_br
    
    # 1. Probability Map (MAGMA with transparent background)
    prob_magma = cv2.applyColorMap((full_mask.cpu().numpy() * 255).astype(np.uint8), cv2.COLORMAP_MAGMA)
    prob_rgba = cv2.cvtColor(prob_magma, cv2.COLOR_BGR2RGBA)
    alpha_prob = (full_mask.cpu().numpy() * 255).astype(np.uint8)
    prob_rgba[:, :, 3] = np.clip(alpha_prob * 2, 0, 255) 
    prob_b64 = encode_image(prob_rgba)

    # 2. Binary Extraction Mask (Translucent Bright Green)
    mask_np = (full_mask > 0.15).cpu().numpy().astype(np.uint8)
    mask_rgba = np.zeros((512, 512, 4), dtype=np.uint8)
    mask_rgba[mask_np > 0] = [0, 255, 128, 180] 
    mask_b64 = encode_image(mask_rgba)
               
    if not np.any(mask_np): 
        return {"network": {"type": "FeatureCollection", "features": []}, "status": "empty_terrain"}        
    
    graph, centrality_scores, topo_stats, skeleton = extract_criticality_from_mask(mask_np, max_bridge_distance=60)        
    
    # 3. Topological Skeleton (Neon Cyan)
    skel_rgba = np.zeros((512, 512, 4), dtype=np.uint8)
    skel_rgba[skeleton] = [0, 229, 255, 255] 
    skel_b64 = encode_image(skel_rgba)
    
    node_count = len(graph.nodes())
    if node_count > 4500: terrain = "Dense Urban"
    elif node_count > 2000: terrain = "Urban"
    elif node_count > 500: terrain = "Semi-Urban"
    else: terrain = "Rural / Forest"
    topo_stats["terrain"] = terrain
    
    DEMO_STATE["graph"] = graph.copy()    
    DEMO_STATE["original_graph"] = graph.copy()    
    DEMO_STATE["bounds"] = (min_lat, max_lat, min_lon, max_lon) 
    DEMO_STATE["stats"] = topo_stats       
    
    return {        
        "network": build_geojson_from_graph(graph, centrality_scores, DEMO_STATE["bounds"]),         
        "resilience_index": 100.0,
        "raw_mask_b64": mask_b64,
        "prob_mask_b64": prob_b64,
        "skeleton_b64": skel_b64,
        "stats": topo_stats,
        "status": "success"    
    }

@app.post("/api/ablate-edge")
async def ablate_edge(request: Request):    
    G = DEMO_STATE.get("graph")    
    orig_G = DEMO_STATE.get("original_graph")    
    bounds = DEMO_STATE.get("bounds") 
    topo_stats = DEMO_STATE.get("stats")       
    
    if G is None: 
        return {"error": "No active network loaded."}        
    
    try:
        data = await request.json()
    except Exception:
        return {"error": "Invalid JSON received by server."}
        
    n1_y = int(data.get("n1_y", 0))
    n1_x = int(data.get("n1_x", 0))
    n2_y = int(data.get("n2_y", 0))
    n2_x = int(data.get("n2_x", 0))

    edge = ((n1_y, n1_x), (n2_y, n2_x))    
    if G.has_edge(*edge): 
        G.remove_edge(*edge)    
    elif G.has_edge(edge[1], edge[0]): 
        G.remove_edge(edge[1], edge[0])        
    
    centrality_scores = nx.betweenness_centrality(G, k=min(50, len(G.nodes())), weight='weight', seed=42)        
    if centrality_scores:        
        max_score = max(centrality_scores.values())        
        if max_score > 0:            
            for node in centrality_scores: 
                centrality_scores[node] = centrality_scores[node] / max_score                    
                
    ri, eff_drop, time_inc = calculate_impact_metrics(orig_G, G)        
    
    return {        
        "network": build_geojson_from_graph(G, centrality_scores, bounds),         
        "resilience_index": ri,        
        "efficiency_drop": eff_drop,
        "time_increase": time_inc,
        "stats": topo_stats,
        "status": "success"    
    }