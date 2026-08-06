from fastapi import FastAPI, HTTPException
import random
import string

app = FastAPI()
rooms = {}

def generate_room_id():
    while True:
        room_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        if room_id not in rooms:
            return room_id

@app.get("/")
def home():
    return {"status": "Server is Running"}

@app.post("/create_room")
def create_room(host_ip: str):
    room_id = generate_room_id()
    rooms[room_id] = host_ip
    return {"room_id": room_id, "status": "Success"}

@app.get("/join_room/{room_id}")
def join_room(room_id: str):
    if room_id in rooms:
        host_ip = rooms[room_id]
        del rooms[room_id]
        return {"host_ip": host_ip, "status": "Connected"}
    else:
        raise HTTPException(status_code=404, detail="Invalid Room ID")
        