import os
import json
from typing import Dict, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# room -> set(websocket)
rooms: Dict[str, Set[WebSocket]] = {}


@app.get("/health")
def health():
    return PlainTextResponse("ok")


@app.get("/")
def home():
    # bezpečné čítanie index.html aj na hostingu
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "index.html")
    if not os.path.isfile(path):
        # ak nie je, hneď uvidíš prečo
        return PlainTextResponse("index.html not found next to server.py", status_code=500)

    with open(path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


async def broadcast(room: str, payload: dict):
    dead = []
    for ws in rooms.get(room, set()):
        try:
            await ws.send_text(json.dumps(payload, ensure_ascii=False))
        except Exception:
            dead.append(ws)

    for ws in dead:
        rooms.get(room, set()).discard(ws)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    room = "general"
    user = "user"

    try:
        # first message = hello
        hello_raw = await ws.receive_text()
        hello = json.loads(hello_raw)

        if hello.get("type") == "hello":
            room = str(hello.get("room", "general"))[:32]
            user = str(hello.get("user", "user"))[:24]

        rooms.setdefault(room, set()).add(ws)
        await broadcast(room, {"type": "system", "text": f"🟢 {user} joined #{room}"})

        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            t = msg.get("type")

            if t == "msg":
                text = str(msg.get("text", ""))[:800]
                await broadcast(room, {"type": "msg", "user": user, "text": text})

            elif t == "set_room":
                new_room = str(msg.get("room", "general"))[:32]
                if new_room != room:
                    rooms.get(room, set()).discard(ws)
                    await broadcast(room, {"type": "system", "text": f"🟡 {user} left"})
                    room = new_room
                    rooms.setdefault(room, set()).add(ws)
                    await broadcast(room, {"type": "system", "text": f"🟢 {user} joined #{room}"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        # pomôže v logoch
        print("WS ERROR:", repr(e))
    finally:
        rooms.get(room, set()).discard(ws)
        try:
            await broadcast(room, {"type": "system", "text": f"🔴 {user} left"})
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port)