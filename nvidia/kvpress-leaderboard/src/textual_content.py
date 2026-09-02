SCRIPT_CODE = """
# Evaluation Script
Run the following command to evaluate your KV cache compression method:

```bash
python -m kvpress.evaluation --method your_method --dataset ruler --model meta-llama/Meta-Llama-3.1-8B-Instruct
```

For detailed instructions and additional parameters, visit our [evaluation guide](https://github.com/NVIDIA/kvpress/tree/main/evaluation).
"""

TITLE = "<h1 style='text-align: center; font-size: 40px;'> KVPress: KV Cache Compression Leaderboard</h1>"

INTRO_TEXT = """
<div style='text-align: center; margin: 20px 0;'>
<p style='font-size: 20px; margin-bottom: 15px;'>
<strong><a href="https://github.com/NVIDIA/kvpress" target="_blank">NVIDIA/KVPress</a></strong> is a comprehensive library for compressing the KV cache of transformer models, featuring multiple state-of-the-art compression methods benchmarked using 🤗 transformers.
</p>
</div>
"""

MOTIVATION_TEXT = """
# 💡 Why KV Cache Compression
- Deploying long-context LLMs is costly due to the linear growth of the key-value (KV) cache in transformer models. For example, handling 1M tokens with Llama 3.1-70B in float16 requires up to **330GB of memory**.
- [NVIDIA/KVPress](https://github.com/NVIDIA/kvpress) implements multiple KV cache compression methods and benchmarks using Hugging Face transformers, aiming to simplify the development of new methods for researchers and developers in this field.
- **Full Transparency**: We care about reproducibility and transparency. Each method in our leaderboard includes **direct links to the source code and original research papers**, along with the exact press initialization commands used for each experiment.
"""

SUBMISSION_INSTRUCTIONS = """
# 📝 How to Submit Your Results

We are happy to welcome contributions to the library and to the leaderboard! Submit your results to the leaderboard by following these simple steps:

1. **🔧 Implement your method** in KVPress.
2. **▶️ Run evaluation** using our provided script.
3. **📤 Submit results** via Pull Request to this repository.

# Detailed Steps

### Step 1: Prepare Your Method
Implement your compression technique using the KVPress framework. Implementing a new press is very easy, you can check an example [here]((https://github.com/NVIDIA/kvpress/blob/main/notebooks/new_press.ipynb).

### Step 2: Run Evaluation
Execute the evaluation script on Ruler dataset with Llama3.1-8B. Evaluation in KVPress is run in one line:
```bash
python evaluation.py --method <your_method> --dataset ruler --model meta-llama/Meta-Llama-3.1-8B-Instruct
```
For a complete guide on evaluation, check the [evaluation guide](https://github.com/NVIDIA/kvpress/tree/main/evaluation).

### Step 3: Collect Results
The script generates a directory with the following structure:

```bash
<your_experiment_directory>/
├── predictions.csv
├── metrics.json
├── config.yaml
```

### Step 4: Submit to Leaderboard
**Fork** this repository, **add your experiment directory** to the `benchmark/` directory in this repository, and **create a PR** with title: `Add <method_name> results`.

## 📋 Requirements
- Compatible with Llama3.1-8B model
- Evaluated on Ruler 4096 dataset
- Follows KVPress implementation standards

Questions? [Contact us](https://github.com/NVIDIA/kvpress/) or open an issue!
"""

ABOUT_TEXT = """
## 🎯 Why KV Cache Compression Matters

Deploying long-context Large Language Models faces a critical bottleneck: **memory consumption**. The key-value (KV) cache in transformer models grows linearly with sequence length, creating significant deployment challenges.
**Llama 3.1-70B** processing **1M tokens** requires up to **330GB of memory** (float16). Memory costs scale linearly with context length, and hardware limitations restrict practical deployment.

**KVPress** addresses these challenges by implementing compression methods from recent research, providing standardized benchmarks for fair comparison, and integrating seamlessly with 🤗 transformers.

Effective KV cache compression enables **Longer contexts** with existing hardware, **Reduced deployment costs** for production systems, and **Broader accessibility** of long-context LLMs.

Contribute to the project by submitting your results to the leaderboard or by adding your method to the library.
"""

CITATION_TEXT = """
## 📚 Citation

If you use KVPress in your research, please cite our paper:

```bibtex
@article{devoto2025expectedattention,
  title={Expected Attention: KV Cache Compression by Estimating Attention from Future Queries Distribution},
  author={Devoto, Alessio and Jeblick, Maximilian and J{\'e}gou, Simon},
  journal={arXiv preprint arXiv:2510.00636},
  year={2025},
  url={https://arxiv.org/abs/2510.00636}
}
```

**Links**: [GitHub](https://github.com/NVIDIA/kvpress) | [Paper](https://arxiv.org/abs/2510.00636) | [Blog](https://huggingface.co/blog/nvidia/kvpress) | [Colab Demo](https://colab.research.google.com/drive/1JNvaTKuuAHrl49dYB9-mdEH_y52Ib-NP)
"""
