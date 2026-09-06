import os
import uuid

import boto3
import requests
from openai import OpenAI
from flask import Blueprint, current_app, jsonify, request, send_from_directory
from flask_jwt_extended import get_jwt_identity, jwt_required

from app.extensions import db, limiter
from app.models import Conversation, Device, Message
from app.utils.errors import error_response
import logging
logger = logging.getLogger(__name__)

bp = Blueprint("ai", __name__)

_BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(_BASE, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

VOICE_MAP = {
    "en": "Matthew",
    "hi": "Aditi",
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

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


# ─── CORE HELPERS (used by both HTTP endpoints and the bridge) ─────────────────

def _get_llm_client() -> OpenAI:
    logger.debug("Creating Gemini (OpenAI-compatible) client")
    return OpenAI(
        api_key=current_app.config["GEMINI_API_KEY"],
        base_url=GEMINI_BASE_URL,
    )


def _run_tts_sync(text: str, voice: str, path: str) -> None:
    """Synthesize speech via Amazon Polly. Requires Flask app context."""
    region = current_app.config.get("S3_REGION", "ap-south-1")
    polly = boto3.client("polly", region_name=region)
    engine = "neural" if voice == "Matthew" else "standard"
    response = polly.synthesize_speech(
        Text=text,
        OutputFormat="mp3",
        VoiceId=voice,
        Engine=engine,
    )
    with open(path, "wb") as f:
        f.write(response["AudioStream"].read())
    logger.info("TTS audio generated voice=%s bytes=%s", voice, os.path.getsize(path))


def run_stt(wav_bytes: bytes, lang: str = "hi") -> str:
    """Transcribe WAV bytes via Deepgram REST API. Requires Flask app context."""
    api_key = current_app.config.get("DEEPGRAM_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPGRAM_API_KEY not configured")

    lang_map = {"hi": "hi", "en": "en"}
    language = lang_map.get(lang, "hi")

    resp = requests.post(
        "https://api.deepgram.com/v1/listen",
        params={
            "model": "nova-3",
            "language": language,
            "punctuate": "true",
        },
        headers={
            "Authorization": f"Token {api_key}",
            "Content-Type": "audio/wav",
        },
        data=wav_bytes,
        timeout=60,
    )
    resp.raise_for_status()
    result = resp.json()
    transcript = result["results"]["channels"][0]["alternatives"][0]["transcript"]
    logger.info("STT completed language=%s audio_bytes=%s", language, len(wav_bytes))
    return transcript.strip()


def run_ask(
    question: str,
    conv_id: str | None = None,
    temperature: float = 0.7,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
) -> str:
    """Call the Gemini LLM with conversation history. Requires Flask app context."""
    history: list[Message] = []
    if conv_id:
        history = (
            Message.query.filter_by(conv_id=conv_id)
            .order_by(Message.ts.asc())
            .limit(MAX_HISTORY)
            .all()
        )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        if msg.role in ("user", "assistant"):
            messages.append({"role": msg.role, "content": msg.text})
    messages.append({"role": "user", "content": question})

    response = _get_llm_client().chat.completions.create(
        model=current_app.config["GEMINI_MODEL"],
        temperature=temperature,
        top_p=1.0,
        messages=messages,
    )
    answer = response.choices[0].message.content
    logger.info("AI response generated conv_id=%s history_messages=%s", conv_id, len(history))

    if conv_id:
        db.session.add(Message(conv_id=conv_id, role="user", text=question))
        db.session.add(Message(conv_id=conv_id, role="assistant", text=answer))
        db.session.commit()

    return answer


def run_tts(
    text: str,
    lang: str = "en",
    base_url: str = "",
    conv_id: str | None = None,
) -> tuple[str, str]:
    """Generate TTS MP3. Returns (audio_url, filename). Requires Flask app context.

    If conv_id is given, attaches the audio_url to the most recent assistant
    message in that conversation (the text/answer is already recorded by run_ask).
    """
    voice = VOICE_MAP.get(lang, VOICE_MAP["en"])
    audio_id = uuid.uuid4().hex
    filename = f"{audio_id}.mp3"
    filepath = os.path.join(UPLOAD_DIR, filename)
    _run_tts_sync(text, voice, filepath)

    s3_url = _upload_to_s3(filepath, filename)
    if s3_url:
        os.remove(filepath)
        audio_url = s3_url
    else:
        audio_url = f"{base_url}/v1/ai/audio/{filename}"

    if conv_id:
        last_reply = (
            Message.query.filter_by(conv_id=conv_id, role="assistant")
            .order_by(Message.ts.desc())
            .first()
        )
        if last_reply:
            last_reply.audio_url = audio_url
            db.session.commit()

            logger.info("TTS completed filename=%s stored remotely=%s", filename, bool(s3_url))
    return audio_url, filename


def _upload_to_s3(filepath: str, key: str) -> str | None:
    try:
        from app.s3 import upload
        return upload(filepath, key)
    except Exception:
        logger.warning("[S3] Upload skipped, using local fallback")
        logger.warning("[S3] Upload error details:", exc_info=True)
        return None


# ─── HTTP ENDPOINTS ───────────────────────────────────────────────────────────

@bp.get("/audio/<filename>")
def serve_audio(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@bp.post("/stt")
@jwt_required()
@limiter.limit("60 per minute")
def speech_to_text():
    user_id = get_jwt_identity()
    lang = request.form.get("lang", "hi")
    conv_id = request.form.get("conv_id")

    audio_file = request.files.get("file")
    if not audio_file:
        return error_response("VALIDATION_FAILED", "Audio file required.", 400)

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
        text = run_stt(audio_file.read(), lang=lang)
        logger.info("STT request completed user_id=%s conv_id=%s", user_id, conv_id)
        return jsonify({"language": lang, "text": text, "conv_id": conv_id})
    except Exception as e:
        logger.exception("STT request failed user_id=%s conv_id=%s", user_id, conv_id)
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
    user_id = get_jwt_identity()
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    lang = data.get("lang", "en")
    conv_id = data.get("conv_id")

    if not text:
        return error_response("VALIDATION_FAILED", "text is required.", 400)

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
        base = request.host_url.rstrip("/")
        audio_url, filename = run_tts(text, lang=lang, base_url=base, conv_id=conv_id)
        return jsonify({"audio_url": audio_url, "filename": filename, "conv_id": conv_id})
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
