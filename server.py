from datetime import datetime
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

app = FastAPI()


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        await websocket.send_text(json.dumps(message, ensure_ascii=False))

    async def broadcast(self, message: dict):
        dead_connections = []

        for connection in self.active_connections:
            try:
                await connection.send_text(json.dumps(message, ensure_ascii=False))
            except Exception:
                dead_connections.append(connection)

        for connection in dead_connections:
            self.disconnect(connection)


manager = ConnectionManager()


@app.get("/")
async def get_index():
    return FileResponse("index.html")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)

    await manager.broadcast({
        "type": "system",
        "message": "Nový používateľ sa pripojil.",
        "time": datetime.now().strftime("%H:%M")
    })

    try:
        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)

            username = data.get("username", "User").strip() or "User"
            message = data.get("message", "").strip()

            if not message:
                continue

            await manager.broadcast({
                "type": "chat",
                "username": username,
                "message": message,
                "time": datetime.now().strftime("%H:%M")
            })

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast({
            "type": "system",
            "message": "Používateľ sa odpojil.",
            "time": datetime.now().strftime("%H:%M")
        })
