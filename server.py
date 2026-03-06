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

# websocket -> {"user": ..., "room": ...}
clients: Dict[WebSocket, dict] = {}

# room -> message history
history: Dict[str, List[dict]] = {}

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


def get_room_users(room: str) -> List[str]:
    users = []
    for ws in rooms.get(room, set()):
        info = clients.get(ws)
        if info and info.get("room") == room:
            users.append(info.get("user", "user"))
    # unique + sorted
    return sorted(list(set(users)), key=str.lower)


async def send_user_list(room: str):
    payload = {
        "type": "users",
        "room": room,
        "users": get_room_users(room)
    }

    dead = []
    for ws in rooms.get(room, set()):
        ok = await safe_send(ws, payload)
        if not ok:
            dead.append(ws)

    for ws in dead:
        rooms.get(room, set()).discard(ws)
        clients.pop(ws, None)


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
        clients.pop(ws, None)


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
        clients[ws] = {"user": user, "room": room}

        # pošli históriu a zoznam online userov
        await send_history(ws, room)
        await send_user_list(room)

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
                    old_room = room

                    rooms.get(old_room, set()).discard(ws)

                    room = new_room
                    rooms.setdefault(room, set()).add(ws)
                    clients[ws] = {"user": user, "room": room}

                    await send_history(ws, room)
                    await send_user_list(old_room)
                    await send_user_list(room)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print("WS ERROR:", repr(e))
    finally:
        old_info = clients.get(ws)
        old_room = old_info.get("room") if old_info else room

        rooms.get(old_room, set()).discard(ws)
        clients.pop(ws, None)

        try:
            await send_user_list(old_room)
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("server:app", host="0.0.0.0", port=port)
