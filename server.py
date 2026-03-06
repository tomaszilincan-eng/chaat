import os
import json
from typing import Dict, Set, List

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

# room -> active sockets
rooms: Dict[str, Set[WebSocket]] = {}

# room -> message history
history: Dict[str, List[dict]] = {}

# koľko správ držať v pamäti na room
MAX_HISTORY = 100


@app.get("/health")
def health():
    return PlainTextResponse("ok")


@app.get("/")
def home():
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "index.html")
    if not os.path.isfile(path):
        return PlainTextResponse("index.html not found next to server.py", status_code=500)

    with open(path, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


def add_to_history(room: str, payload: dict):
    history.setdefault(room, []).append(payload)
    if len(history[room]) > MAX_HISTORY:
        history[room] = history[room][-MAX_HISTORY:]


async def safe_send(ws: WebSocket, payload: dict) -> bool:
    try:
        await ws.send_text(json.dumps(payload, ensure_ascii=False))
        return True
    except Exception:
        return False


async def broadcast(room: str, payload: dict, save: bool = True):
    if save:
        add_to_history(room, payload)

    dead = []
    for ws in rooms.get(room, set()):
        ok = await safe_send(ws, payload)
        if not ok:
            dead.append(ws)

    for ws in dead:
        rooms.get(room, set()).discard(ws)


async def send_history(ws: WebSocket, room: str):
    items = history.get(room, [])
    await safe_send(ws, {
        "type": "history",
        "items": items
    })


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()

    room = "general"
    user = "user"

    try:
        hello_raw = await ws.receive_text()
        hello = json.loads(hello_raw)

        if hello.get("type") == "hello":
            room = str(hello.get("room", "general"))[:32]
            user = str(hello.get("user", "user"))[:24]

        rooms.setdefault(room, set()).add(ws)

        # najprv pošli históriu, aby user videl čo zmeškal
        await send_history(ws, room)

        join_msg = {"type": "system", "text": f"🟢 {user} joined #{room}"}
        await broadcast(room, join_msg, save=True)

        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            t = msg.get("type")

            if t == "msg":
                text = str(msg.get("text", "")).strip()[:800]
                if text:
                    await broadcast(
                        room,
                        {"type": "msg", "user": user, "text": text},
                        save=True
                    )

            elif t == "ping":
                await safe_send(ws, {"type": "pong"})

            elif t == "set_room":
                new_room = str(msg.get("room", "general"))[:32]
                if new_room != room:
                    rooms.get(room, set()).discard(ws)
                    await broadcast(room, {"type": "system", "text": f"🟡 {user} left"}, save=True)

                    room = new_room
                    rooms.setdefault(room, set()).add(ws)

                    # po zmene room pošli históriu novej room
                    await send_history(ws, room)
                    await broadcast(room, {"type": "system", "text": f"🟢 {user} joined #{room}"}, save=True)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print("WS ERROR:", repr(e))
    finally:
        rooms.get(room, set()).discard(ws)
        try:
            await broadcast(room, {"type": "system", "text": f"🔴 {user} left"}, save=True)
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port)
