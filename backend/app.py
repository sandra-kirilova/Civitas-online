from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit, join_room
from game import Game
import random
import string

app = Flask(__name__)
app.config["SECRET_KEY"] = "civitas-secret"

# SocketIO server (API starp backend ↔ frontend)
socketio = SocketIO(app, cors_allowed_origins="*")

# In-memory room storage: room_code -> Game instance
ROOMS = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def generate_room_code(length: int = 4) -> str:
    """Ģenerē unikālu istabas kodu, piem. ABKF."""
    while True:
        code = "".join(random.choice(string.ascii_uppercase) for _ in range(length))
        if code not in ROOMS:
            return code


def get_game(room_code: str) -> Game | None:
    return ROOMS.get(room_code)


def find_player_by_sid(room_code: str, sid: str):
    """
    Atrod spēlētāju konkrētā istabā pēc Socket.IO session ID.
    Atgriež (game, player_id) vai (game, None).
    """
    game = get_game(room_code)
    if not game:
        return None, None
    for pid, pdata in game.players.items():
        if pdata.get("sid") == sid:
            return game, pid
    return game, None


# ---------------------------------------------------------------------------
# Vienkāršs REST health-check
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Socket.IO eventu API
# ---------------------------------------------------------------------------

@socketio.on("create_room")
def handle_create_room(data):
    """
    data: { "name": "Player name" }
    """
    name = (data or {}).get("name") or "Spēlētājs"

    room_code = generate_room_code()
    game = Game(room_code)
    ROOMS[room_code] = game

    # Pievienojam spēlētāju
    player_id = game.add_player(name=name, sid=request.sid)
    game.deal_initial_hand(player_id)

    join_room(room_code)

    # Sūtām pilno privāto stāvokli šim spēlētājam
    emit(
        "your_state",
        {
            "room_code": room_code,
            "player_id": player_id,
            "me": game.private_state_for(player_id),
        },
    )

    # Sūtām publisko stāvokli visiem istabā (šobrīd tikai šis spēlētājs)
    emit("game_update", game.public_state(), room=room_code)


@socketio.on("join_room")
def handle_join_room(data):
    """
    data: { "room_code": "ABCD", "name": "Player name" }
    """
    data = data or {}
    room_code = (data.get("room_code") or "").upper()
    name = data.get("name") or "Spēlētājs"

    game = get_game(room_code)
    if not game:
        emit("error_message", {"error": "Room not found"})
        return

    player_id = game.add_player(name=name, sid=request.sid)
    game.deal_initial_hand(player_id)

    join_room(room_code)

    # privātais stāvoklis
    emit(
        "your_state",
        {
            "room_code": room_code,
            "player_id": player_id,
            "me": game.private_state_for(player_id),
        },
    )

    # publiskais stāvoklis visiem
    socketio.emit("game_update", game.public_state(), room=room_code)


@socketio.on("draw_cards")
def handle_draw_cards(data):
    """
    data: { "room_code": "ABCD" }
    Spēlētājs vienmēr velk līdz 5 kārtīm.
    """
    data = data or {}
    room_code = (data.get("room_code") or "").upper()

    game, player_id = find_player_by_sid(room_code, request.sid)
    if not game or not player_id:
        emit("error_message", {"error": "Invalid room or player"})
        return

    game.draw_up_to_hand_limit(player_id)

    # atjauninām šī spēlētāja rokas / galda info
    emit(
        "your_state",
        {
            "room_code": room_code,
            "player_id": player_id,
            "me": game.private_state_for(player_id),
        },
    )
    # atjauninām publisko stāvokli visiem
    socketio.emit("game_update", game.public_state(), room=room_code)


@socketio.on("play_card")
def handle_play_card(data):
    """
    data: {
      "room_code": "ABCD",
      "card_id": "<uuid>",
      "target_player_id": "<optional>",
      "extra": {...optional info...}
    }
    """
    data = data or {}
    room_code = (data.get("room_code") or "").upper()
    card_id = data.get("card_id")
    target_player_id = data.get("target_player_id")
    extra = data.get("extra") or {}

    game, player_id = find_player_by_sid(room_code, request.sid)
    if not game or not player_id:
        emit("error_message", {"error": "Invalid room or player"})
        return

    result = game.play_card(player_id, card_id, target_player_id, extra)

    # pēc katras izspēles – velkam līdz pilnai rokai (5)
    game.draw_up_to_hand_limit(player_id)

    # rezultāts aktīvajam spēlētājam
    emit("action_result", result)

    # privātais stāvoklis aktīvajam
    emit(
        "your_state",
        {
            "room_code": room_code,
            "player_id": player_id,
            "me": game.private_state_for(player_id),
        },
    )

    # publiskais stāvoklis visiem
    socketio.emit("game_update", game.public_state(), room=room_code)


@socketio.on("reshuffle_deck")
def handle_reshuffle_deck(data):
    """
    Manuāls pārjaukšanas triggers, ja gribēsim UI pogu.
    data: { "room_code": "ABCD" }
    """
    data = data or {}
    room_code = (data.get("room_code") or "").upper()
    game = get_game(room_code)
    if not game:
        emit("error_message", {"error": "Room not found"})
        return

    # vienkāršs pārjaukšanas mehānisms
    game.deck.extend(game.discard_pile)
    game.discard_pile = []
    game._shuffle_deck()

    socketio.emit("game_update", game.public_state(), room=room_code)


@socketio.on("disconnect")
def handle_disconnect():
    """
    Ja kāds atslēdzas – izņemam viņu no spēles.
    """
    sid = request.sid
    to_delete_rooms = []
    for room_code, game in list(ROOMS.items()):
        removed_id = game.remove_player_by_sid(sid)
        if removed_id:
            # atjauninām pārējiem istabā
            socketio.emit("game_update", game.public_state(), room=room_code)
            if not game.players:
                to_delete_rooms.append(room_code)

    for rc in to_delete_rooms:
        del ROOMS[rc]


if __name__ == "__main__":
    # lokālai palaišanai / Codespace u.tml.
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
