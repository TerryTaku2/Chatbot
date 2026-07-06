from flask import session
from flask_socketio import emit, join_room, leave_room

from . import socketio
from .db_ttech import get_db


@socketio.on("connect")
def on_connect():
    if "user_id" not in session:
        return False  # reject
    uid = session["user_id"]
    join_room(f"user_{uid}")  # personal room for targeted notifications
    with get_db() as conn:
        conn.execute("UPDATE users SET last_seen=CURRENT_TIMESTAMP WHERE id=?", (uid,))
        conn.commit()


@socketio.on("join_conv")
def on_join(data):
    if "user_id" not in session:
        return
    uid     = session["user_id"]
    conv_id = data.get("conv_id")
    with get_db() as conn:
        member = conn.execute(
            "SELECT 1 FROM conversation_members WHERE conversation_id=? AND user_id=?",
            (conv_id, uid)
        ).fetchone()
    if member:
        join_room(f"conv_{conv_id}")
        emit("joined", {"conv_id": conv_id})


@socketio.on("leave_conv")
def on_leave(data):
    conv_id = data.get("conv_id")
    leave_room(f"conv_{conv_id}")


@socketio.on("send_msg")
def on_send_message(data):
    if "user_id" not in session:
        return
    uid     = session["user_id"]
    conv_id = data.get("conv_id")
    content = (data.get("content") or "").strip()

    if not content or not conv_id:
        return

    with get_db() as conn:
        member = conn.execute(
            "SELECT 1 FROM conversation_members WHERE conversation_id=? AND user_id=?",
            (conv_id, uid)
        ).fetchone()
        if not member:
            return

        cur = conn.execute(
            "INSERT INTO messages (conversation_id, sender_id, content) VALUES (?,?,?) RETURNING id",
            (conv_id, uid, content)
        )
        msg_id = cur.fetchone()["id"]

        conn.execute(
            "UPDATE conversations SET updated_at=CURRENT_TIMESTAMP WHERE id=?", (conv_id,)
        )
        conn.execute(
            "UPDATE conversation_members SET last_read_at=CURRENT_TIMESTAMP WHERE conversation_id=? AND user_id=?",
            (conv_id, uid)
        )
        conn.commit()

        msg_row = conn.execute(
            "SELECT m.*, u.full_name as sender_name, u.role as sender_role FROM messages m JOIN users u ON m.sender_id=u.id WHERE m.id=?",
            (msg_id,)
        ).fetchone()

    emit("new_msg", dict(msg_row), room=f"conv_{conv_id}")


@socketio.on("typing")
def on_typing(data):
    if "user_id" not in session:
        return
    uid     = session["user_id"]
    conv_id = data.get("conv_id")
    with get_db() as conn:
        if not conn.execute(
            "SELECT 1 FROM conversation_members WHERE conversation_id=? AND user_id=?",
            (conv_id, uid)
        ).fetchone():
            return
    emit("typing_update", {
        "user_id":   uid,
        "user_name": session.get("user_name"),
        "typing":    data.get("typing", False),
    }, room=f"conv_{conv_id}", include_self=False)
