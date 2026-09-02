import torch
import torch.nn as nn
from torch.nn import functional as F
from dataclasses import dataclass
@dataclass
class GPTConfig:
    vocab_size: int = 65      
    block_size: int = 256    
    n_embd: int = 384         
    n_head: int = 6           
    n_layer: int = 6          
    dropout: float = 0.2   
    bias: bool = False
    qkv_bias: bool = False
    nonlinearity: str = 'relu'
    weight_tying: bool = False
    lm_head_bias: bool = True  

class CausalSelfAttention(nn.Module):
    def __init__(self, config):
        super().__init__()
        assert config.n_embd % config.n_head == 0
        self.config = config
        
        self.c_attn = nn.Linear(config.n_embd, 3 * config.n_embd, bias=config.qkv_bias)
        self.c_proj = nn.Linear(config.n_embd, config.n_embd, bias=config.bias)
        
        self.attn_dropout = nn.Dropout(config.dropout)
        self.resid_dropout = nn.Dropout(config.dropout)
        
        self.register_buffer('tril', torch.tril(torch.ones(config.block_size, config.block_size))
                             .view(1, 1, config.block_size, config.block_size), persistent=False)

    def forward(self, x):
        B, T, C = x.shape

        qkv = self.c_attn(x)
        q, k, v = qkv.split(self.config.n_embd, dim=-1)

        hs = C // self.config.n_head
        q = q.view(B, T, self.config.n_head, hs).transpose(1, 2)
        k = k.view(B, T, self.config.n_head, hs).transpose(1, 2)
        v = v.view(B, T, self.config.n_head, hs).transpose(1, 2)

        wei = (q @ k.transpose(-2, -1)) * (hs ** -0.5)
        wei = wei.masked_fill(self.tril[:, :, :T, :T] == 0, float('-inf'))
        wei = F.softmax(wei, dim=-1)
        wei = self.attn_dropout(wei)

        out = wei @ v
        out = out.transpose(1, 2).contiguous().view(B, T, C)
        out = self.c_proj(out)
        out = self.resid_dropout(out)
        return out

class FeedForward(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.c_fc = nn.Linear(config.n_embd, 4 * config.n_embd, bias=config.bias)
        self.act = nn.ReLU() if config.nonlinearity == 'relu' else nn.GELU(approximate='tanh')
        self.c_proj = nn.Linear(4 * config.n_embd, config.n_embd, bias=config.bias)
        self.dropout = nn.Dropout(config.dropout)

    def forward(self, x):
        x = self.c_fc(x)
        x = self.act(x)
        x = self.c_proj(x)
        return self.dropout(x)

class Block(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.ln_1 = nn.LayerNorm(config.n_embd)
        self.attn = CausalSelfAttention(config) 
        self.ln_2 = nn.LayerNorm(config.n_embd)
        self.mlp = FeedForward(config)
    def forward(self, x):
        # (B, T, n_embd) -> (B, T, n_embd)
        # Pre-norm: normalize into each branch, keep the residual stream itself untouched.
        x = x + self.attn(self.ln_1(x))
        x = x + self.mlp(self.ln_2(x))
        return x
    
class GPTLanguageModel(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.transformer = nn.ModuleDict(dict(
            wte = nn.Embedding(config.vocab_size, config.n_embd),
            wpe = nn.Embedding(config.block_size, config.n_embd),
            drop = nn.Dropout(config.dropout),
            h = nn.ModuleList([Block(config) for _ in range(config.n_layer)]),
            ln_f = nn.LayerNorm(config.n_embd),
        ))
        self.lm_head = nn.Linear(config.n_embd, config.vocab_size, bias=config.lm_head_bias)
        if config.weight_tying:
            self.lm_head.weight = self.transformer.wte.weight

    def forward(self, idx, targets=None):
        B, T = idx.shape
        pos = torch.arange(0, T, dtype=torch.long, device=idx.device)
        tok_emb = self.transformer.wte(idx)
        pos_emb = self.transformer.wpe(pos)
        x = self.transformer.drop(tok_emb + pos_emb)
        for block in self.transformer.h:
            x = block(x)
        x = self.transformer.ln_f(x)
        if targets is not None:
            logits = self.lm_head(x)
            loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1))
        else:
            logits = self.lm_head(x[:, [-1], :]) 
            loss = None
        return logits, loss
    
    def generate(self, idx, max_new_tokens, temperature=1.0, top_k=None):
        for _ in range(max_new_tokens):
            idx_cond = idx[:, -self.config.block_size:] 
            logits, loss = self(idx_cond)
            logits = logits[:, -1, :] 
            logits = logits / temperature
            if top_k is not None:
                k = min(top_k, logits.size(-1))
                v, _ = torch.topk(logits, k)
                logits[logits < v[:, [-1]]] = float('-inf')
            probs = F.softmax(logits, dim=-1)
            idx_next = torch.multinomial(probs, num_samples=1)
            idx = torch.cat((idx, idx_next), dim=1)
        return idx
    
    @classmethod
    def from_pretrained(cls, model_type: str):
        assert model_type in {'gpt2', 'gpt2-medium', 'gpt2-large', 'gpt2-xl'}
        from transformers import GPT2LMHeadModel
        print(f"Loading weights from pretrained gpt: {model_type}")
        config_args = {
            'gpt2':        dict(n_layer=12, n_head=12, n_embd=768),   
            'gpt2-medium': dict(n_layer=24, n_head=16, n_embd=1024), 
            'gpt2-large':  dict(n_layer=36, n_head=20, n_embd=1280),  
            'gpt2-xl':     dict(n_layer=48, n_head=25, n_embd=1600), 
        }[model_type]
        config = GPTConfig(
            vocab_size=50257, 
            block_size=1024,
            bias=True,        
            qkv_bias=True,     
            nonlinearity='gelu',   
            weight_tying=True,    
            lm_head_bias=False,
            **config_args
        )
        model = GPTLanguageModel(config)
        num_params = sum(p.numel() for p in model.parameters())
        if model_type == 'gpt2':
            assert num_params == 124439808, f"Parameter count mismatch: {num_params} != 124439808"
        sd = model.state_dict()
        sd_keys = [k for k in sd.keys() if not k.endswith('.attn.tril')]
        model_hf = GPT2LMHeadModel.from_pretrained(model_type, torch_dtype=torch.float32)
        sd_hf = model_hf.state_dict()
        sd_keys_hf = [k for k in sd_hf.keys() if not k.endswith('.attn.masked_bias')]
        sd_keys_hf = [k for k in sd_keys_hf if not k.endswith('.attn.bias')]
        assert len(sd_keys) == len(sd_keys_hf), f"mismatched keys: {len(sd_keys)} != {len(sd_keys_hf)}"
        transposed = ['.attn.c_attn.weight', '.attn.c_proj.weight', '.mlp.c_fc.weight', '.mlp.c_proj.weight']
        for k in sd_keys_hf:
            if any(k.endswith(w) for w in transposed):
                assert sd_hf[k].t().shape == sd[k].shape, f"Shape mismatch at {k}"
                with torch.no_grad():
                    sd[k].copy_(sd_hf[k].t())
            else:
                assert sd_hf[k].shape == sd[k].shape, f"Shape mismatch at {k}"
                with torch.no_grad():
                    sd[k].copy_(sd_hf[k])
        return model

@torch.no_grad()
def estimate_loss(model, device, eval_iters):
    from data import get_batch
    out = {}
    model.eval()
    for split in ['train', 'val']:
        losses = torch.zeros(eval_iters)
        for k in range(eval_iters):
            X, Y = get_batch(split)
            X, Y = X.to(device), Y.to(device)
            logits, loss = model(X, Y)
            losses[k] = loss.item()
        out[split] = losses.mean()   
    model.train()
    return out

if __name__ == "__main__":
    from data import get_batch, vocab_size, decode, block_size
    learning_rate = 3e-4
    max_iters = 5000
    eval_interval = 500
    eval_iters = 200
    device = 'cuda' if torch.cuda.is_available() else 'mps' if torch.backends.mps.is_available() else 'cpu'
    torch.manual_seed(1337)
    config = GPTConfig(
        vocab_size=vocab_size, 
        block_size=block_size,
        bias=True,        
        qkv_bias=False,     
        nonlinearity='relu',   
        weight_tying=False,    
        lm_head_bias=True       
    )
    model = GPTLanguageModel(config)
    model = model.to(device)
    num_params = sum(p.numel() for p in model.parameters())
    assert num_params == 10788929, f"Parameter count mismatch: {num_params} != 10788929"
    optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)
    best_val = float('inf')

    for iter in range(max_iters):
        
        # Full train/val evaluation every eval_interval steps.
        if iter % eval_interval == 0 or iter == max_iters - 1:
            losses = estimate_loss(model, device, eval_iters)
            print(f"step {iter:4d}: train loss = {losses['train']:.4f}, val loss = {losses['val']:.4f}")
            if losses['val'] < best_val:
                best_val = losses['val']
                torch.save(model.state_dict(), 'gpt_shakespeare.pt')
                print(f"--- checkpoint updated, best val loss so far: {best_val:.4f} ---")

        xb, yb = get_batch('train') 
        xb, yb = xb.to(device), yb.to(device) 
        logits, loss = model(xb, yb) 
        optimizer.zero_grad(set_to_none=True)
        loss.backward()                    
        optimizer.step()

    model.eval()                   
    context = torch.zeros((1, 1), dtype=torch.long, device=device)
    generated_tokens = model.generate(context, max_new_tokens=100)
    print(decode(generated_tokens[0].tolist()))