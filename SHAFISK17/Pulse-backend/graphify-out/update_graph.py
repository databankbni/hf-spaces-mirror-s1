import os
import sys
import json
import subprocess
from pathlib import Path

def main():
    print("[graphify update] Starting incremental update...")
    
    # 1. Paths
    backend_path = Path('C:/Users/HP/Desktop/Segmento/SegmentoPulse-Backend/SegmentoPulse/backend')
    graphify_out = backend_path / 'graphify-out'
    
    if not graphify_out.exists():
        graphify_out.mkdir(parents=True, exist_ok=True)
        
    # 2. Detect incremental changes
    from graphify.detect import detect_incremental, save_manifest
    
    result = detect_incremental(backend_path)
    new_total = result.get('new_total', 0)
    deleted = list(result.get('deleted_files', []))
    
    print(f"Incremental detection: {new_total} new/changed file(s), {len(deleted)} deleted file(s) to prune.")
    
    # Save incremental state
    (graphify_out / '.graphify_incremental.json').write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    
    if new_total == 0 and not deleted:
        print("[graphify update] No files changed since last run. Nothing to update.")
        return
        
    # 3. Populate .graphify_detect.json
    detect_data = {
        'files': result.get('new_files', {}),
        'all_files': result.get('files', {}),
        'total_files': result.get('new_total', 0),
        'total_words': result.get('total_words', 0),
        'skipped_sensitive': result.get('skipped_sensitive', []),
        'needs_graph': True,
    }
    (graphify_out / '.graphify_detect.json').write_text(json.dumps(detect_data, ensure_ascii=False), encoding="utf-8")
    
    # 4. Check if code only
    code_exts = {'.py','.ts','.js','.go','.rs','.java','.cpp','.c','.rb','.swift','.kt','.cs','.scala','.php','.cc','.cxx','.hpp','.h','.kts','.lua','.toc','.f','.F','.f90','.F90','.f95','.F95','.f03','.F03','.f08','.F08'}
    new_files = result.get('new_files', {})
    all_changed = [f for files in new_files.values() for f in files]
    code_only = all(Path(f).suffix.lower() in code_exts for f in all_changed)
    
    # 5. Part A: AST Extraction for code files
    from graphify.extract import collect_files, extract
    code_files = []
    for f in result.get('new_files', {}).get('code', []):
        code_files.extend(collect_files(Path(f)) if Path(f).is_dir() else [Path(f)])
        
    if code_files:
        print(f"[graphify update] Extracting AST for {len(code_files)} code files...")
        ast_result = extract(code_files, cache_root=backend_path)
        (graphify_out / '.graphify_ast.json').write_text(json.dumps(ast_result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"AST Extraction complete: {len(ast_result['nodes'])} nodes, {len(ast_result['edges'])} edges")
    else:
        ast_result = {'nodes':[],'edges':[],'input_tokens':0,'output_tokens':0}
        (graphify_out / '.graphify_ast.json').write_text(json.dumps(ast_result, ensure_ascii=False), encoding="utf-8")
        print("No code files to extract AST from.")
        
    # 6. Part B: Semantic Extraction
    semantic_result = {'nodes':[],'edges':[],'hyperedges':[],'input_tokens':0,'output_tokens':0}
    print("[graphify update] Running semantic extraction on new/changed files...")
    
    # Get all changed files (including code files for semantic relationship extraction)
    semantic_files = []
    for category, files in result.get('new_files', {}).items():
        semantic_files.extend(files)
            
    if semantic_files:
        from graphify.cache import check_semantic_cache, save_semantic_cache
        cached_nodes, cached_edges, cached_hyperedges, uncached = check_semantic_cache(semantic_files)
        print(f"Cache hit: {len(semantic_files) - len(uncached)} files, {len(uncached)} files need extraction.")
        
        # Save cached to temp
        (graphify_out / '.graphify_cached.json').write_text(json.dumps({
            'nodes': cached_nodes,
            'edges': cached_edges,
            'hyperedges': cached_hyperedges
        }, ensure_ascii=False), encoding="utf-8")
        
        new_nodes, new_edges, new_hyperedges = [], [], []
        input_tokens, output_tokens = 0, 0
        
        if uncached:
            openrouter_key = os.environ.get('OPENROUTER_API_KEY')
            gemini_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
            
            if openrouter_key:
                from graphify.llm import extract_corpus_parallel
                print(f"Extracting semantics for {len(uncached)} files via OpenRouter API (gpt-oss-120b)...")
                extracted = extract_corpus_parallel([Path(f) for f in uncached], backend="openrouter", api_key=openrouter_key)
                new_nodes = extracted.get('nodes', [])
                new_edges = extracted.get('edges', [])
                new_hyperedges = extracted.get('hyperedges', [])
                input_tokens = extracted.get('input_tokens', 0)
                output_tokens = extracted.get('output_tokens', 0)
                # Save new to cache
                save_semantic_cache(new_nodes, new_edges, new_hyperedges)
            elif gemini_key:
                from graphify.llm import extract_corpus_parallel
                print(f"Extracting semantics for {len(uncached)} files via Gemini API...")
                extracted = extract_corpus_parallel([Path(f) for f in uncached], backend="gemini", api_key=gemini_key)
                new_nodes = extracted.get('nodes', [])
                new_edges = extracted.get('edges', [])
                new_hyperedges = extracted.get('hyperedges', [])
                input_tokens = extracted.get('input_tokens', 0)
                output_tokens = extracted.get('output_tokens', 0)
                # Save new to cache
                save_semantic_cache(new_nodes, new_edges, new_hyperedges)
            else:
                print("WARNING: Neither OPENROUTER_API_KEY nor GEMINI_API_KEY/GOOGLE_API_KEY is set in environment.")
                print("Skipping semantic extraction of uncached files.")
                
        # Merge cached and new
        all_nodes = cached_nodes + new_nodes
        all_edges = cached_edges + new_edges
        all_hyperedges = cached_hyperedges + new_hyperedges
        
        # Dedup nodes by id
        seen = set()
        deduped_nodes = []
        for n in all_nodes:
            if n['id'] not in seen:
                seen.add(n['id'])
                deduped_nodes.append(n)
                
        semantic_result = {
            'nodes': deduped_nodes,
            'edges': all_edges,
            'hyperedges': all_hyperedges,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
        }
        
    (graphify_out / '.graphify_semantic.json').write_text(json.dumps(semantic_result, indent=2, ensure_ascii=False), encoding="utf-8")
        
    # 7. Part C: Merge AST and Semantic
    ast = json.loads((graphify_out / '.graphify_ast.json').read_text(encoding="utf-8"))
    sem = json.loads((graphify_out / '.graphify_semantic.json').read_text(encoding="utf-8"))
    
    seen = {n['id'] for n in ast['nodes']}
    merged_nodes = list(ast['nodes'])
    for n in sem['nodes']:
        if n['id'] not in seen:
            merged_nodes.append(n)
            seen.add(n['id'])
            
    merged_edges = ast['edges'] + sem['edges']
    merged_hyperedges = sem.get('hyperedges', [])
    
    merged_extract = {
        'nodes': merged_nodes,
        'edges': merged_edges,
        'hyperedges': merged_hyperedges,
        'input_tokens': sem.get('input_tokens', 0),
        'output_tokens': sem.get('output_tokens', 0),
    }
    (graphify_out / '.graphify_extract.json').write_text(json.dumps(merged_extract, indent=2, ensure_ascii=False), encoding="utf-8")
    
    # 8. Merge with existing graph
    existing_graph = graphify_out / 'graph.json'
    if existing_graph.exists():
        # Backup
        import shutil
        shutil.copy2(existing_graph, graphify_out / '.graphify_old.json')
        
    from graphify.build import build_merge, build_from_json
    
    # Run build_merge
    G = build_merge(
        [merged_extract],
        graph_path=str(existing_graph) if existing_graph.exists() else None,
        prune_sources=deleted or None,
    )
    print(f"[graphify update] Merged graph has {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
    
    # Write merged result back to .graphify_extract.json so Step 4/analysis sees the full graph
    merged_out = {
        'nodes': [{'id': n, **d} for n, d in G.nodes(data=True)],
        'edges': [
            {**{k: val for k, val in d.items() if k not in ('_src', '_tgt', 'source', 'target')},
             'source': d.get('_src', u), 'target': d.get('_tgt', v)}
            for u, v, d in G.edges(data=True)
        ],
        'hyperedges': list(G.graph.get('hyperedges', [])),
        'input_tokens': merged_extract.get('input_tokens', 0),
        'output_tokens': merged_extract.get('output_tokens', 0),
    }
    (graphify_out / '.graphify_extract.json').write_text(json.dumps(merged_out, ensure_ascii=False), encoding="utf-8")
    
    # Save manifest for next runs
    save_manifest(result['files'])
    
    # 9. Clustering & Analysis
    from graphify.cluster import cluster, score_all
    from graphify.analyze import god_nodes, surprising_connections, suggest_questions
    from graphify.report import generate
    from graphify.export import to_json
    
    print("[graphify update] Running clustering and analysis...")
    communities = cluster(G)
    cohesion = score_all(G, communities)
    tokens = {'input': merged_extract.get('input_tokens', 0), 'output': merged_extract.get('output_tokens', 0)}
    gods = god_nodes(G)
    surprises = surprising_connections(G, communities)
    
    # Load or generate community labels
    labels = {}
    labels_file = graphify_out / '.graphify_labels.json'
    if labels_file.exists():
        try:
            old_labels = json.loads(labels_file.read_text(encoding="utf-8"))
            labels = {int(k): v for k, v in old_labels.items()}
        except Exception:
            pass
            
    # For any new communities, add default labels
    for cid in communities:
        if cid not in labels:
            labels[cid] = f"Community {cid}"
            
    questions = suggest_questions(G, communities, labels)
    
    report = generate(G, communities, cohesion, labels, gods, surprises, detect_data, tokens, str(backend_path), suggested_questions=questions)
    (graphify_out / 'GRAPH_REPORT.md').write_text(report, encoding="utf-8")
    
    # Export raw graph
    to_json(G, communities, str(existing_graph), force=True)
    
    analysis = {
        'communities': {str(k): v for k, v in communities.items()},
        'cohesion': {str(k): v for k, v in cohesion.items()},
        'gods': gods,
        'surprises': surprises,
        'questions': questions,
    }
    (graphify_out / '.graphify_analysis.json').write_text(json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8")
    (graphify_out / '.graphify_labels.json').write_text(json.dumps({str(k): v for k, v in labels.items()}, ensure_ascii=False), encoding="utf-8")
    
    # Show diff if backup exists
    old_backup = graphify_out / '.graphify_old.json'
    if old_backup.exists():
        try:
            from graphify.analyze import graph_diff
            from networkx.readwrite import json_graph
            old_data = json.loads(old_backup.read_text(encoding="utf-8"))
            G_old = json_graph.node_link_graph(old_data, edges='links')
            diff = graph_diff(G_old, G)
            print("\n=== Graph Changes ===")
            print(diff['summary'])
            if diff['new_nodes']:
                print('New nodes:', ', '.join(n['label'] for n in diff['new_nodes'][:5]))
            if diff['new_edges']:
                print('New edges:', len(diff['new_edges']))
        except Exception as e:
            print(f"Could not compute graph diff: {e}")
            
    # 10. Generate HTML viz
    print("[graphify update] Generating HTML visualization...")
    try:
        subprocess.run([sys.executable, "-m", "graphify", "export", "html"], cwd=str(backend_path), check=True)
    except Exception:
        try:
            subprocess.run(["graphify", "export", "html"], cwd=str(backend_path), shell=True, check=True)
        except Exception as e:
            print(f"Error generating HTML viz: {e}")
            
    # 11. Cost tracking and cleanup
    input_tok = merged_extract.get('input_tokens', 0)
    output_tok = merged_extract.get('output_tokens', 0)
    
    cost_path = graphify_out / 'cost.json'
    if cost_path.exists():
        try:
            cost = json.loads(cost_path.read_text(encoding="utf-8"))
        except Exception:
            cost = {'runs': [], 'total_input_tokens': 0, 'total_output_tokens': 0}
    else:
        cost = {'runs': [], 'total_input_tokens': 0, 'total_output_tokens': 0}
        
    import time
    cost['runs'].append({
        'date': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'input_tokens': input_tok,
        'output_tokens': output_tok,
        'files': detect_data.get('total_files', 0),
    })
    cost['total_input_tokens'] += input_tok
    cost['total_output_tokens'] += output_tok
    cost_path.write_text(json.dumps(cost, indent=2, ensure_ascii=False), encoding="utf-8")
    
    # Cleanup temp files
    temp_files = [
        '.graphify_detect.json',
        '.graphify_extract.json',
        '.graphify_ast.json',
        '.graphify_semantic.json',
        '.graphify_analysis.json',
        '.graphify_old.json',
        '.graphify_cached.json'
    ]
    for tf in temp_files:
        fpath = graphify_out / tf
        if fpath.exists():
            try:
                fpath.unlink()
            except Exception:
                pass
                
    print("\n=== Update Complete ===")
    print(f"Merged: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, {len(communities)} communities")
    print(f"This run: {input_tok:,} input tokens, {output_tok:,} output tokens")
    print(f"All time: {cost['total_input_tokens']:,} input, {cost['total_output_tokens']:,} output")

if __name__ == "__main__":
    main()
