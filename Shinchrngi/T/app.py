import gradio as gr
import time

# 初始玩家雲端數據 (模擬正版)
player_data = {
    "coins": 500,
    "cash": 30,
    "level": 1,
    "xp": 0,
    "barn_capacity": 70,
    "inventory": {"小麥": 0, "玉米": 0, "雞飼料": 0, "雞蛋": 0, "麵包": 0, "餅乾": 0}
}

def get_status():
    inv_str = ", ".join([f"{k}:{v}" for k, v in player_data["inventory"].items()])
    return f"🌟 等級: {player_data['level']} | 🪙 金幣: {player_data['coins']} | 💚 綠鈔: {player_data['cash']} | 📦 穀倉: {sum(player_data['inventory'].values())}/{player_data['barn_capacity']}\n🎒 倉庫內容: {inv_str}"

def plant_crop(crop):
    current_total = sum(player_data["inventory"].values())
    if current_total >= player_data["barn_capacity"]:
        return "❌ 穀倉爆倉了！無法收成！", get_status()
    player_data["inventory"][crop] += 1
    player_data["xp"] += 1
    if player_data["xp"] >= player_data["level"] * 10:
        player_data["level"] += 1
        player_data["xp"] = 0
    return f"🌾 成功種植並收成 1 個{crop}！(正版規則：獲得 1 XP)", get_status()

def make_factory(product):
    inv = player_data["inventory"]
    if product == "雞飼料":
        if inv["小麥"] < 2: return "❌ 材料不足！需要 2 小麥", get_status()
        inv["小麥"] -= 2
        inv["雞飼料"] += 1
    elif product == "麵包":
        if inv["小麥"] < 3: return "❌ 材料不足！需要 3 小麥", get_status()
        inv["小麥"] -= 3
        inv["麵包"] += 1
    elif product == "餅乾":
        if inv["小麥"] < 2 or inv["雞蛋"] < 2: return "❌ 材料不足！需要 2小麥 + 2雞蛋", get_status()
        inv["小麥"] -= 2
        inv["雞蛋"] -= 2
        inv["餅乾"] += 1
    player_data["xp"] += 3
    return f"🏭 工廠運作成功！做出 1 個{product}！", get_status()

def launch_drone():
    inv = player_data["inventory"]
    if inv["麵包"] >= 1 and inv["雞飼料"] >= 1:
        inv["麵包"] -= 1
        inv["雞飼料"] -= 1
        player_data["coins"] += 150
        player_data["xp"] += 10
        return "🚀 無人機成功發射！村民狂讚！獲得 🪙150 金幣, 🌟10 XP", get_status()
    return "❌ 沒有符合無人機需求的訂單商品 (需要 1麵包 + 1雞飼料)", get_status()

def gm_modify(coins, cash, level, barn):
    if coins: player_data["coins"] = int(coins)
    if cash: player_data["cash"] = int(cash)
    if level: player_data["level"] = int(level)
    if barn: player_data["barn_capacity"] = int(barn)
    return "⚡ 上帝權限：全球數據修改成功！", get_status()

with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🚜 正版技術指標《夢想小鎮》AI 掛機全功能網頁版")
    
    status_box = gr.Textbox(value=get_status(), label="📊 當前小鎮雲端同步狀態 (支援跨裝置登入)", interactive=False)
    log_box = gr.Textbox(value="歡迎來到小鎮！請開始經營或啟動上帝後台。", label="📢 遊戲日誌")
    
    with gr.Tab("🌾 農田與工廠生產線"):
        with gr.Row():
            btn_wheat = gr.Button("種植小麥 (正版5分/測試即時)")
            btn_corn = gr.Button("種植玉米 (正版30分/測試即時)")
        with gr.Row():
            btn_feed = gr.Button("🏭 飼料廠 (2小麥 -> 1雞飼料)")
            btn_bread = gr.Button("🏭 麵包店 (3小麥 -> 1麵包)")
            btn_cookie = gr.Button("🏭 點心廠 (2小麥+2雞蛋 -> 1餅乾)")
            
    with gr.Tab("🚀 無人機/直升機出貨板"):
        btn_drone = gr.Button("發射無人機訂單 (消耗: 1麵包 + 1雞飼料 -> 賺 150金幣)")
        
    with gr.Tab("🔑 秘密上帝控制後台"):
        gr.Markdown("### ⚠️ 全球數據分離控制面板 (密碼路由：/ggghhh.gguiyyggvvjhbxghjjgobh)")
        with gr.Row():
            input_coins = gr.Number(label="修改總金幣")
            input_cash = gr.Number(label="修改綠鈔")
            input_level = gr.Number(label="直接改等級")
            input_barn = gr.Number(label="一鍵滿級穀倉容量")
        btn_gm = gr.Button("⚡ 執行上帝暴力修改", variant="stop")

    btn_wheat.click(fn=lambda: plant_crop("小麥"), outputs=[log_box, status_box])
    btn_corn.click(fn=lambda: plant_crop("玉米"), outputs=[log_box, status_box])
    btn_feed.click(fn=lambda: make_factory("雞飼料"), outputs=[log_box, status_box])
    btn_bread.click(fn=lambda: make_factory("麵包"), outputs=[log_box, status_box])
    btn_cookie.click(fn=lambda: make_factory("餅乾"), outputs=[log_box, status_box])
    btn_drone.click(fn=lambda: launch_drone(), outputs=[log_box, status_box])
    btn_gm.click(fn=gm_modify, inputs=[input_coins, input_cash, input_level, input_barn], outputs=[log_box, status_box])

demo.launch()
