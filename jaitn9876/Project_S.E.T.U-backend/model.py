import torch
import torch.nn as nn

class TransformerBlock(nn.Module):
    """
    Hybrid Transformer Block: Captures global dependencies (the 'Transformer' requirement).
    """
    def __init__(self, embed_dim, num_heads):
        super(TransformerBlock, self).__init__()
        self.attn = nn.MultiheadAttention(embed_dim, num_heads, batch_first=True)
        self.norm1 = nn.LayerNorm(embed_dim)
        self.norm2 = nn.LayerNorm(embed_dim)
        self.mlp = nn.Sequential(
            nn.Linear(embed_dim, embed_dim * 4),
            nn.GELU(),
            nn.Linear(embed_dim * 4, embed_dim)
        )

    def forward(self, x):
        # Flatten for attention: [B, C, H, W] -> [B, N, C]
        b, c, h, w = x.shape
        x_flat = x.flatten(2).transpose(1, 2)
        
        # Self-Attention
        attn_out, _ = self.attn(x_flat, x_flat, x_flat)
        x_flat = self.norm1(x_flat + attn_out)
        
        # Feed Forward
        mlp_out = self.mlp(x_flat)
        x_flat = self.norm2(x_flat + mlp_out)
        
        # Reshape back: [B, N, C] -> [B, C, H, W]
        return x_flat.transpose(1, 2).view(b, c, h, w)

class ConvBlock(nn.Module):
    def __init__(self, ch_in, ch_out):
        super(ConvBlock, self).__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(ch_in, ch_out, 3, 1, 1, bias=True), nn.BatchNorm2d(ch_out), nn.ReLU(inplace=True),
            nn.Conv2d(ch_out, ch_out, 3, 1, 1, bias=True), nn.BatchNorm2d(ch_out), nn.ReLU(inplace=True)
        )
    def forward(self, x): return self.conv(x)

class UpConv(nn.Module):
    def __init__(self, ch_in, ch_out):
        super(UpConv, self).__init__()
        self.up = nn.Sequential(
            nn.Upsample(scale_factor=2),
            nn.Conv2d(ch_in, ch_out, 3, 1, 1, bias=True), nn.BatchNorm2d(ch_out), nn.ReLU(inplace=True)
        )
    def forward(self, x): return self.up(x)

class AttentionUNet(nn.Module):
    """
    TransUNet Hybrid: Uses CNN for local extraction and Transformer for global context.
    """
    def __init__(self, img_ch=3, output_ch=1):
        super(AttentionUNet, self).__init__()
        self.Maxpool = nn.MaxPool2d(kernel_size=2, stride=2)
        self.Conv1 = ConvBlock(img_ch, 64)
        self.Conv2 = ConvBlock(64, 128)
        self.Conv3 = ConvBlock(128, 256)
        
        # Transformer bottleneck to capture long-range dependencies
        self.Transformer = TransformerBlock(embed_dim=256, num_heads=4)
        
        self.Up3 = UpConv(256, 128)
        self.Up_conv3 = ConvBlock(256, 128)
        self.Up2 = UpConv(128, 64)
        self.Up_conv2 = ConvBlock(128, 64)
        self.Conv_1x1 = nn.Conv2d(64, output_ch, 1, 1, 0)

    def forward(self, x):
        x1 = self.Conv1(x)
        x2 = self.Maxpool(x1)
        x2 = self.Conv2(x2)
        x3 = self.Maxpool(x2)
        x3 = self.Conv3(x3)

        # Apply Transformer logic at the deepest level (bottleneck)
        x3 = self.Transformer(x3)

        d3 = self.Up3(x3)
        d3 = torch.cat((x2, d3), dim=1)
        d3 = self.Up_conv3(d3)

        d2 = self.Up2(d3)
        d2 = torch.cat((x1, d2), dim=1)
        d2 = self.Up_conv2(d2)

        return self.Conv_1x1(d2)