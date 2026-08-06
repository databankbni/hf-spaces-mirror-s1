import sys
import os
import argparse
import logging
from pathlib import Path
import networkx as nx
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.features.causal_discovery import (
    clean_data,
    fix_skewness,
    remove_outliers,
    run_pc_algorithm,
    run_ges_algorithm,
    run_lingam_algorithm,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

def print_dot_string(cg_graph, labels, output_dir, title):
    """
    Generates and saves a DOT string of the DAG for use in DoWhy models.
    """
    try:
        nodes = cg_graph.get_nodes()
        edges = cg_graph.get_graph_edges()
    except AttributeError:
        return
        
    node_to_label = {node.get_name(): labels[i] for i, node in enumerate(nodes)}
    
    print(f"\n# ==========================================")
    print(f"# DOT String for {title}")
    print(f"# (Copy this into your DoWhy model!)")
    print(f"# ==========================================\n")
    print("digraph {")
    dot_lines = ["digraph {"]
    
    for edge in edges:
        node1 = node_to_label[edge.get_node1().get_name()]
        node2 = node_to_label[edge.get_node2().get_name()]
        
        ep1_str = str(edge.get_endpoint1())
        ep2_str = str(edge.get_endpoint2())
        
        # Only output clear directed edges for DoWhy
        if "TAIL" in ep1_str and "ARROW" in ep2_str:
            line = f"    {node1} -> {node2};"
            print(line)
            dot_lines.append(line)
        elif "ARROW" in ep1_str and "TAIL" in ep2_str:
            line = f"    {node2} -> {node1};"
            print(line)
            dot_lines.append(line)
            
    print("}\n")
    dot_lines.append("}")
    
    # Save to file
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        file_name = "pc_causal_graph.dot" if "PC" in title else "ges_causal_graph.dot"
        file_path = os.path.join(output_dir, file_name)
        with open(file_path, "w") as f:
            f.write("\n".join(dot_lines))
        logger.info(f"Saved DOT string to {file_path}")

def print_lingam_dot_string(adj_matrix, labels, output_dir, title):
    """
    Generates and saves a DOT string for LiNGAM's adjacency matrix.
    In LiNGAM's adjacency matrix B, B[i, j] != 0 means j -> i.
    """
    print(f"\n# ==========================================")
    print(f"# DOT String for {title}")
    print(f"# (Copy this into your DoWhy model!)")
    print(f"# ==========================================\n")
    print("digraph {")
    dot_lines = ["digraph {"]
    
    n_vars = len(labels)
    for i in range(n_vars):
        for j in range(n_vars):
            if adj_matrix[i, j] != 0:
                # j -> i
                line = f"    {labels[j]} -> {labels[i]};"
                print(line)
                dot_lines.append(line)
                
    print("}\n")
    dot_lines.append("}")
    
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        file_path = os.path.join(output_dir, "lingam_causal_graph.dot")
        with open(file_path, "w") as f:
            f.write("\n".join(dot_lines))
        logger.info(f"Saved DOT string to {file_path}")

def draw_causal_graph(cg_graph, labels, output_path, title):
    """
    Draw a causal graph using NetworkX and Matplotlib to avoid GraphViz system dependencies.
    """
    G = nx.DiGraph()
    
    # In causal-learn, nodes can be accessed via cg_graph.get_nodes()
    # and edges via cg_graph.get_graph_edges()
    try:
        nodes = cg_graph.get_nodes()
        edges = cg_graph.get_graph_edges()
    except AttributeError:
        logger.error("Could not extract nodes/edges from the causal graph object.")
        return
        
    # Map from node object (or node name X1, X2) to our actual feature labels
    node_to_label = {node.get_name(): labels[i] for i, node in enumerate(nodes)}
        
    for node in nodes:
        G.add_node(node_to_label[node.get_name()])
        
    for edge in edges:
        # Edge types in causal-learn: Endpoint.TAIL (--) and Endpoint.ARROW (->)
        # We simplify to directed edges where an arrow exists
        node1 = node_to_label[edge.get_node1().get_name()]
        node2 = node_to_label[edge.get_node2().get_name()]
        
        # Check endpoints (1: tail, 2: arrow)
        # Just add a directed edge from node1 to node2 as a simplified visualization
        # In PC, edge endpoint types indicate causal direction or bidirected/undirected
        endpoint1 = edge.get_endpoint1()
        endpoint2 = edge.get_endpoint2()
        
        # Convert to string to check type
        ep1_str = str(endpoint1)
        ep2_str = str(endpoint2)
        
        if "TAIL" in ep1_str and "ARROW" in ep2_str:
            G.add_edge(node1, node2)
        elif "ARROW" in ep1_str and "TAIL" in ep2_str:
            G.add_edge(node2, node1)
        elif "ARROW" in ep1_str and "ARROW" in ep2_str:
            # Bidirected
            G.add_edge(node1, node2, style='dashed')
            G.add_edge(node2, node1, style='dashed')
        else:
            # Undirected
            G.add_edge(node1, node2, style='dotted')

    plt.figure(figsize=(10, 8))
    pos = nx.spring_layout(G, seed=42)
    
    # Draw nodes
    nx.draw_networkx_nodes(G, pos, node_size=2000, node_color='lightblue', alpha=0.9)
    
    # Draw edges based on style
    solid_edges = [(u, v) for u, v, d in G.edges(data=True) if d.get('style', 'solid') == 'solid']
    dashed_edges = [(u, v) for u, v, d in G.edges(data=True) if d.get('style', 'solid') == 'dashed']
    dotted_edges = [(u, v) for u, v, d in G.edges(data=True) if d.get('style', 'solid') == 'dotted']
    
    nx.draw_networkx_edges(G, pos, edgelist=solid_edges, width=2, arrows=True, arrowsize=20)
    nx.draw_networkx_edges(G, pos, edgelist=dashed_edges, width=2, arrows=True, arrowsize=20, style='dashed')
    nx.draw_networkx_edges(G, pos, edgelist=dotted_edges, width=2, arrows=False, style='dotted')
    
    # Draw labels
    nx.draw_networkx_labels(G, pos, font_size=12, font_family="sans-serif", font_weight="bold")
    
    plt.title(title, fontsize=16)
    plt.axis('off')
    plt.tight_layout()
    
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    logger.info(f"Saved causal graph visualization to {output_path}")

def draw_lingam_graph(adj_matrix, labels, output_path, title):
    G = nx.DiGraph()
    for label in labels:
        G.add_node(label)
        
    n_vars = len(labels)
    for i in range(n_vars):
        for j in range(n_vars):
            if adj_matrix[i, j] != 0:
                # Add the weight to the edge, rounded to 2 decimal places
                G.add_edge(labels[j], labels[i], weight=round(adj_matrix[i, j], 2))
                
    plt.figure(figsize=(10, 8))
    pos = nx.spring_layout(G, seed=42)
    nx.draw_networkx_nodes(G, pos, node_size=2000, node_color='lightblue', alpha=0.9)
    nx.draw_networkx_edges(G, pos, width=2, arrows=True, arrowsize=20)
    nx.draw_networkx_labels(G, pos, font_size=12, font_family="sans-serif", font_weight="bold")
    
    # Extract weights and draw them on the edges
    edge_labels = nx.get_edge_attributes(G, 'weight')
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=11, font_color='darkred', font_weight='bold')
    
    plt.title(title, fontsize=16)
    plt.axis('off')
    plt.tight_layout()
    
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    logger.info(f"Saved LiNGAM graph visualization to {output_path}")

def main():
    parser = argparse.ArgumentParser(description="Run Causal Discovery Pipeline")
    parser.add_argument("--data", type=str, default="data/processed/super_model_data_clean.csv", help="Path to input CSV data")
    parser.add_argument("--output_dir", type=str, default="artifacts", help="Directory to save output graphs")
    parser.add_argument("--algorithm", type=str, choices=["pc", "ges", "lingam", "all"], default="lingam", help="Causal algorithm to run")
    parser.add_argument("--sample_size", type=int, default=5000, help="Max rows to process (for speed)")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        logger.error(f"Data file not found: {data_path}")
        return

    logger.info(f"Loading data from {data_path}")
    df = pd.read_csv(data_path)
    
    # 1. Clean Data
    logger.info("--- Step 1: Cleaning Data ---")
    df = clean_data(df)
    
    # Limit sample size for faster causal discovery
    if len(df) > args.sample_size:
        logger.info(f"Subsampling to {args.sample_size} rows for faster processing...")
        df = df.sample(args.sample_size, random_state=42)

    # 2. Fix Skewness
    logger.info("--- Step 2: Fixing Skewness ---")
    df = fix_skewness(df)
    
    # 3. Remove Outliers
    logger.info("--- Step 3: Removing Outliers ---")
    df = remove_outliers(df)
    
    # For meaningful discovery, select relevant columns
    cols_of_interest = ['price', 'competitor_price', 'inventory', 'demand', 'day_of_week']
    existing_cols = [c for c in cols_of_interest if c in df.columns]
    
    if not existing_cols:
        logger.error("Could not find relevant pricing columns in dataset.")
        # Fallback to just using numeric columns
        existing_cols = list(df.select_dtypes(include=[np.number]).columns[:10])
        
    df_causal = df[existing_cols]
    
    os.makedirs(args.output_dir, exist_ok=True)
    
    # 4. Run Algorithms
    if args.algorithm in ["pc", "all", "both"]:
        logger.info("--- Step 4a: Running PC Algorithm ---")
        cg_pc, pc_labels = run_pc_algorithm(df_causal)
        draw_causal_graph(cg_pc.G, pc_labels, os.path.join(args.output_dir, "pc_causal_graph.png"), "Causal Graph (PC Algorithm)")
        print_dot_string(cg_pc.G, pc_labels, args.output_dir, "PC Algorithm")
        
    if args.algorithm in ["ges", "all", "both"]:
        logger.info("--- Step 4b: Running GES Algorithm ---")
        try:
            cg_ges, ges_labels = run_ges_algorithm(df_causal)
            draw_causal_graph(cg_ges, ges_labels, os.path.join(args.output_dir, "ges_causal_graph.png"), "Causal Graph (GES Algorithm)")
        except Exception as e:
            logger.error(f"GES Algorithm failed (likely due to NumPy 2.x compatibility issues in causal-learn): {e}")

    if args.algorithm in ["lingam", "all"]:
        logger.info("--- Step 4c: Running LiNGAM Algorithm ---")
        adj_matrix, lingam_labels = run_lingam_algorithm(df_causal)
        draw_lingam_graph(adj_matrix, lingam_labels, os.path.join(args.output_dir, "lingam_causal_graph.png"), "Causal Graph (LiNGAM)")
        print_lingam_dot_string(adj_matrix, lingam_labels, args.output_dir, "LiNGAM Algorithm")

if __name__ == "__main__":
    main()
