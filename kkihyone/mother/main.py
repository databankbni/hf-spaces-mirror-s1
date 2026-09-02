import os
import urllib.parse
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/photos", StaticFiles(directory="photos"), name="photos")

templates = Jinja2Templates(directory="templates")

PHOTOS_ROOT = "photos"
FOLDERS = {
    "고복저수지": {"name": "고복저수지", "caption": "고복저수지에서의 평온한 풍경"},
    "고성여행": {"name": "고성여행", "caption": "푸른 바다와 함께한 고성 여행"},
    "부산여행": {"name": "부산여행", "caption": "부산에서 보낸 따뜻한 시간"},
    "새만금": {"name": "새만금", "caption": "탁 트인 새만금 방조제를 달리며"},
    "여수마지막여행": {"name": "여수마지막여행", "caption": "엄마와 마지막으로 함께한 여수여행"},
    "외암민속마을": {"name": "외암민속마을", "caption": "고즈넉한 외암민속마을의 옛 정취"},
    "제주도여행": {"name": "제주도여행", "caption": "아름다운 섬 제주에서의 기억"},
    "탕정과시골": {"name": "탕정과시골", "caption": "마음이 편안해지는 탕정과 시골 풍경"},
    "태우졸업식": {"name": "태우졸업식", "caption": "축하와 감동이 가득했던 태우 졸업식"}
}

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    all_images_data = {}
    for folder_key, info in FOLDERS.items():
        folder_path = os.path.join(PHOTOS_ROOT, folder_key)
        images = []
        if os.path.exists(folder_path):
            images = [
                f"photos/{folder_key}/{urllib.parse.quote(f)}" 
                for f in sorted(os.listdir(folder_path)) 
                if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp'))
            ]
        all_images_data[folder_key] = {
            "name": info["name"],
            "images": images,
            "caption": info["caption"]
        }
    return templates.TemplateResponse("index.html", {"request": request, "folders": all_images_data})

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=7860)