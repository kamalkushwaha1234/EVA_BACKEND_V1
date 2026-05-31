"""
Device bridge — can run standalone or embedded inside the Flask process.

Standalone:  python bridge.py
Embedded:    called from run.py via start_bridge(app)

When a Flask app is provided, the STT/ASK/TTS logic is called directly
(no HTTP, no auth tokens needed). Otherwise it falls back to HTTP calls.
"""

import logging
import json
import os
import socket
import threading
import wave

import paho.mqtt.client as mqtt
import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
MQTT_BROKER = os.environ.get("MQTT_BROKER_HOST", "mff41cf7.ala.asia-southeast1.emqxsl.com")
MQTT_PORT = int(os.environ.get("MQTT_BROKER_PORT", 8883))
MQTT_USER = os.environ.get("MQTT_USER", "toy")
MQTT_PASS = os.environ.get("MQTT_PASS", "")

TOPIC_PUB_RESPONSE = "pc/response"
UDP_PORT = int(os.environ.get("UDP_PORT", 5005))
SAMPLE_RATE = 16000

# HTTP fallback (standalone mode only)
API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:5000")
API_EMAIL = os.environ.get("BRIDGE_EMAIL", "bridge@eva.ai")
API_PASSWORD = os.environ.get("BRIDGE_PASSWORD", "")

audio_chunks: list[bytes] = []
_http_token: str = ""


# ─── NETWORK HELPERS ──────────────────────────────────────────────────────────
def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _public_ip() -> str:
    env_ip = os.environ.get("PUBLIC_IP")
    if env_ip:
        return env_ip
    try:
        resp = requests.get("http://169.254.169.254/latest/meta-data/public-ipv4", timeout=5)
        if resp.status_code == 200:
            return resp.text.strip()
    except Exception:
        pass
    return _local_ip()


MY_IP = _public_ip()


# ─── HTTP FALLBACK (standalone mode) ──────────────────────────────────────────
def _http_login() -> str:
    res = requests.post(
        f"{API_BASE}/v1/auth/login",
        json={"email": API_EMAIL, "password": API_PASSWORD},
        timeout=10,
    )
    res.raise_for_status()
    token = res.json()["access_token"]
    logger.info("[Auth] Logged in as %s", API_EMAIL)
    return token


def _auth() -> dict:
    return {"Authorization": f"Bearer {_http_token}"}


def _pipeline_http(wav_path: str) -> str | None:
    """STT → ASK → TTS over HTTP. Returns audio_url or None."""
    global _http_token

    def _post_stt():
        with open(wav_path, "rb") as f:
            return requests.post(
                f"{API_BASE}/v1/ai/stt",
                files={"file": f},
                data={"lang": "hi"},
                headers=_auth(),
                timeout=60,
            )

    stt_res = _post_stt()
    if stt_res.status_code == 401:
        _http_token = _http_login()
        stt_res = _post_stt()

    if stt_res.status_code != 200:
        logger.error("[STT] Failed (%s): %s", stt_res.status_code, stt_res.text)
        return None

    transcript = stt_res.json().get("text", "").strip()
    conv_id = stt_res.json().get("conv_id")
    logger.info("[STT] %r", transcript)
    if not transcript:
        return None

    ask_res = requests.post(
        f"{API_BASE}/v1/ai/ask",
        json={"question": transcript, "conv_id": conv_id},
        headers=_auth(),
        timeout=60,
    )
    if ask_res.status_code != 200:
        logger.error("[ASK] Failed (%s): %s", ask_res.status_code, ask_res.text)
        return None

    answer = ask_res.json().get("answer", "")
    logger.info("[ASK] %r", answer)

    tts_res = requests.post(
        f"{API_BASE}/v1/ai/tts",
        json={"text": answer, "lang": "hi"},
        headers=_auth(),
        timeout=60,
    )
    if tts_res.status_code != 200:
        logger.error("[TTS] Failed (%s): %s", tts_res.status_code, tts_res.text)
        return None

    return tts_res.json().get("audio_url")


# ─── DIRECT CALL MODE (embedded in Flask process) ─────────────────────────────
def _pipeline_direct(wav_bytes: bytes, flask_app) -> str | None:
    """STT → ASK → TTS by calling the AI functions directly."""
    from app.api.v1.ai import run_stt, run_ask, run_tts

    with flask_app.app_context():
        transcript = run_stt(wav_bytes, lang="hi")
        logger.info("[STT] %r", transcript)
        if not transcript:
            return None

        answer = run_ask(transcript)
        logger.info("[ASK] %r", answer)

        base_url = f"http://{MY_IP}:5000"
        audio_url, _ = run_tts(answer, lang="hi", base_url=base_url)
        return audio_url


# ─── AUDIO PROCESSING ─────────────────────────────────────────────────────────
def _handle_audio(buffer_data: bytes, mqtt_client: mqtt.Client, flask_app=None):
    filename = "recording.wav"
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(buffer_data)
    logger.info("[Bridge] Saved %s (%s bytes)", filename, len(buffer_data))

    if flask_app is not None:
        audio_url = _pipeline_direct(buffer_data, flask_app)
    else:
        audio_url = _pipeline_http(filename)

    if not audio_url:
        return

    logger.info("[MQTT] -> ESP32 play: %s", audio_url)
    mqtt_client.publish(
        TOPIC_PUB_RESPONSE,
        json.dumps({"identifier": "audioplay", "inputParams": {"url": audio_url}}),
    )


# ─── UDP RECEIVER ─────────────────────────────────────────────────────────────
def _udp_loop(mqtt_client: mqtt.Client, flask_app=None):
    global audio_chunks
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", UDP_PORT))
    logger.info("[UDP] Listening on %s:%s...", MY_IP, UDP_PORT)

    while True:
        data, addr = sock.recvfrom(2048)
        try:
            token_len = int.from_bytes(data[0:4], byteorder="big")
            payload = data[4 + token_len:]
            if b"STOP" in payload:
                logger.info("[UDP] STOP from %s", addr)
                if audio_chunks:
                    _handle_audio(b"".join(audio_chunks), mqtt_client, flask_app)
                    audio_chunks = []
            else:
                audio_chunks.append(payload)
                if len(audio_chunks) == 1 or len(audio_chunks) % 25 == 0:
                    logger.info("[UDP] Buffering chunk %s", len(audio_chunks))
        except Exception:
            logger.exception("[UDP] Failed to process incoming packet")


# ─── MQTT ─────────────────────────────────────────────────────────────────────
def _make_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.tls_set()

    def on_connect(client, _userdata, _flags, _rc, _properties=None):
        logger.info("[MQTT] Connected.")
        client.subscribe([
            ("esp32/data", 0),
            ("user/cheekotoy/e4b063b90be8/thing/data/post", 0),
        ])

    def on_message(client, _userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            identifier = data.get("identifier")
            if identifier == "login":
                client.publish(
                    TOPIC_PUB_RESPONSE,
                    json.dumps({
                        "identifier": "updatetoken",
                        "inputParams": {"token": "SECRET"},
                    }),
                )
                logger.info("[MQTT] Received login request, sent token update")
            elif identifier == "data_config":
                client.publish(
                    TOPIC_PUB_RESPONSE,
                    json.dumps({
                        "identifier": "updateconfig",
                        "inputParams": {
                            "udp_host": MY_IP,
                            "udp_port": UDP_PORT,
                            "http_host": MY_IP,
                            "http_port": 5000,
                            "sample_rate": SAMPLE_RATE,
                            "channels": 1,
                        },
                    }),
                )
                logger.info("[MQTT] Received config request, sent config update")
        except Exception:
            logger.exception("[MQTT] Failed to process message")

    client.on_connect = on_connect
    client.on_message = on_message
    return client


# ─── PUBLIC API ───────────────────────────────────────────────────────────────
def start_bridge(flask_app=None):
    """
    Start MQTT and UDP threads as daemons and return immediately.

    Pass a Flask app instance to use direct function calls (embedded mode).
    Leave flask_app=None to use HTTP calls (standalone mode).
    """
    global _http_token

    client = _make_mqtt_client()
    client.connect(MQTT_BROKER, MQTT_PORT)

    threading.Thread(target=client.loop_forever, daemon=True).start()
    threading.Thread(
        target=_udp_loop, args=(client, flask_app), daemon=True
    ).start()

    logger.info("[Bridge] MQTT + UDP threads started.")


# ─── STANDALONE ENTRY POINT ───────────────────────────────────────────────────
if __name__ == "__main__":
    _http_token = _http_login()
    client = _make_mqtt_client()
    client.connect(MQTT_BROKER, MQTT_PORT)
    threading.Thread(target=client.loop_forever, daemon=True).start()
    _udp_loop(client)  # blocking in main thread
