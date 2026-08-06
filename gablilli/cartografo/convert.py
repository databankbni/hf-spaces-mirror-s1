import os, shutil

for font_dir in os.listdir('/tmp/fonts_raw'):
    src = os.path.join('/tmp/fonts_raw', font_dir)
    if os.path.isdir(src):
        dst = os.path.join('/app/fonts', font_dir)
        os.makedirs(dst, exist_ok=True)
        for f in os.listdir(src):
            if f.endswith('.pbf'):
                shutil.copy(os.path.join(src, f), os.path.join(dst, f))

print('Font Noto copiati')
