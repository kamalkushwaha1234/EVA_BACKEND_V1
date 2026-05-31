import asyncio
import os
import subprocess
import threading
import uuid

import edge_tts
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import AssistantMessage, SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential
from flask import Blueprint, current_app, jsonify, request, send_from_directory
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.extensions import db, limiter
from app.models import Conversation, Device, Message
from app.utils.errors import error_response

bp = Blueprint("ai", __name__)

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(_BASE, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

VOICE_MAP = {
    "en": "en-US-AriaNeural",
    "hi": "hi-IN-MadhurNeural",
}

DEFAULT_SYSTEM_PROMPT = (
    "You are an AI tutor for children aged 2 to 17. "
    "Always explain things in simple, easy-to-understand language. "
    "Use fun examples to make concepts clear. "
    "Be friendly, kind, and encouraging at all times. "
    "Keep your answers short and to the point. "
    "Never answer any sexual, violent, or inappropriate questions. "
    "If a question is not suitable for children or is outside the age range of 2-17, "
    "politely refuse and redirect the child to ask a parent or teacher."
)

MAX_HISTORY = 20


# ─── CORE HELPERS (used by both HTTP endpoints and the bridge) ─────────────────

def _get_azure_client() -> ChatCompletionsClient:
    return ChatCompletionsClient(
        endpoint=current_app.config["AZURE_ENDPOINT"],
        credential=AzureKeyCredential(current_app.config["AZURE_TOKEN"]),
    )


def _run_tts_sync(text: str, voice: str, path: str) -> None:
    """Run edge_tts in a fresh thread+event loop to avoid eventlet conflicts."""
    exc_box: list[Exception] = []

    def _target():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                edge_tts.Communicate(text=text, voice=voice).save(path)
            )
        except Exception as e:
            exc_box.append(e)
        finally:
            loop.close()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join()
    if exc_box:
        raise exc_box[0]


def run_stt(wav_bytes: bytes, lang: str = "en") -> str:
    """Transcribe raw WAV bytes via Whisper. Requires Flask app context."""
    audio_id = uuid.uuid4().hex
    audio_path = os.path.join(UPLOAD_DIR, f"{audio_id}.wav")
    output_txt = os.path.join(UPLOAD_DIR, f"{audio_id}.txt")
    try:
        with open(audio_path, "wb") as f:
            f.write(wav_bytes)
        subprocess.run(
            [
                current_app.config["WHISPER_BIN"],
                "-m", current_app.config["WHISPER_MODEL"],
                "-f", audio_path,
                "-l", lang,
                "-t", "1",
                "--no-timestamps",
                "--output-txt",
                "--output-file", os.path.join(UPLOAD_DIR, audio_id),
            ],
            check=True,
            capture_output=True,
        )
        with open(output_txt, "r", encoding="utf-8") as f:
            return f.read().strip()
    finally:
        for p in (audio_path, output_txt):
            if os.path.exists(p):
                os.remove(p)


def run_ask(
    question: str,
    conv_id: str | None = None,
    temperature: float = 0.7,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> str:
    """Call Azure LLM with conversation history. Requires Flask app context."""
    history: list[Message] = []
    if conv_id:
        history = (
            Message.query.filter_by(conv_id=conv_id)
            .order_by(Message.ts.asc())
            .limit(MAX_HISTORY)
            .all()
        )

    messages = [SystemMessage(system_prompt)]
    for msg in history:
        if msg.role == "user":
            messages.append(UserMessage(msg.text))
        elif msg.role == "assistant":
            messages.append(AssistantMessage(msg.text))
    messages.append(UserMessage(question))

    response = _get_azure_client().complete(
        model=current_app.config["AZURE_MODEL"],
        temperature=temperature,
        top_p=1.0,
        messages=messages,
    )
    answer = response.choices[0].message.content

    if conv_id:
        db.session.add(Message(conv_id=conv_id, role="user", text=question))
        db.session.add(Message(conv_id=conv_id, role="assistant", text=answer))
        db.session.commit()

    return answer


def run_tts(text: str, lang: str = "en", base_url: str = "") -> tuple[str, str]:
    """Generate TTS MP3. Returns (audio_url, filename). Requires Flask app context."""
    voice = VOICE_MAP.get(lang, VOICE_MAP["en"])
    audio_id = uuid.uuid4().hex
    filename = f"{audio_id}.mp3"
    filepath = os.path.join(UPLOAD_DIR, filename)
    _run_tts_sync(text, voice, filepath)

    s3_url = _upload_to_s3(filepath, filename)
    if s3_url:
        os.remove(filepath)
        return s3_url, filename

    return f"{base_url}/v1/ai/audio/{filename}", filename


def _upload_to_s3(filepath: str, key: str) -> str | None:
    try:
        from app.s3 import upload
        return upload(filepath, key)
    except Exception:
        logger.warning("[S3] Upload skipped, using local fallback")
        return None


# ─── HTTP ENDPOINTS ───────────────────────────────────────────────────────────

@bp.get("/audio/<filename>")
def serve_audio(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@bp.post("/stt")
@jwt_required()
@limiter.limit("60 per minute")
def speech_to_text():
    lang = request.form.get("lang", "hi")
    conv_id = request.form.get("conv_id")

    audio_file = request.files.get("file")
    if not audio_file:
        return error_response("VALIDATION_FAILED", "Audio file required.", 400)

    try:
        text = run_stt(audio_file.read(), lang=lang)
        return jsonify({"language": lang, "text": text, "conv_id": conv_id})
    except subprocess.CalledProcessError as e:
        return error_response("STT_FAILED", e.stderr.decode(errors="replace"), 500)
    except Exception as e:
        return error_response("STT_FAILED", str(e), 500)


@bp.post("/ask")
@jwt_required()
@limiter.limit("60 per minute")
def ask_llm():
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}

    question = (data.get("question") or "").strip()
    conv_id = data.get("conv_id")
    temperature = float(data.get("temperature", 0.7))
    system_prompt = data.get("system_prompt") or DEFAULT_SYSTEM_PROMPT

    if not question:
        return error_response("VALIDATION_FAILED", "question is required.", 400)

    if conv_id:
        conv = db.session.get(Conversation, conv_id)
        if not conv:
            return error_response("CONVERSATION_NOT_FOUND", "No such conversation.", 404)
        device = db.session.get(Device, conv.device_id)
        if not device or device.owner_id != user_id:
            return error_response(
                "NOT_OWNER", "Not authorized to access this conversation.", 403
            )

    try:
        answer = run_ask(question, conv_id=conv_id, temperature=temperature,
                         system_prompt=system_prompt)
        return jsonify({"question": question, "answer": answer, "conv_id": conv_id})
    except Exception as e:
        return error_response("LLM_FAILED", str(e), 500)


@bp.post("/tts")
@jwt_required()
@limiter.limit("60 per minute")
def text_to_speech():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    lang = data.get("lang", "en")

    if not text:
        return error_response("VALIDATION_FAILED", "text is required.", 400)

    try:
        base = request.host_url.rstrip("/")
        audio_url, filename = run_tts(text, lang=lang, base_url=base)
        return jsonify({"audio_url": audio_url, "filename": filename})
    except Exception as e:
        return error_response("TTS_FAILED", str(e), 500)


@bp.post("/reset/<conv_id>")
@jwt_required()
@limiter.limit("30 per minute")
def reset_conversation(conv_id):
    user_id = get_jwt_identity()
    conv = db.session.get(Conversation, conv_id)
    if not conv:
        return error_response("CONVERSATION_NOT_FOUND", "No such conversation.", 404)
    device = db.session.get(Device, conv.device_id)
    if not device or device.owner_id != user_id:
        return error_response("NOT_OWNER", "Not authorized.", 403)

    Message.query.filter_by(conv_id=conv_id).delete()
    db.session.commit()
    return jsonify({"message": "Conversation history cleared.", "conv_id": conv_id})
