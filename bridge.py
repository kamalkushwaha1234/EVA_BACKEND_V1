"""
Device bridge — can run standalone or embedded inside the Flask process.

Standalone:  python bridge.py
Embedded:    called from run.py via start_bridge(app)

When a Flask app is provided, the STT/ASK/TTS logic is called directly
(no HTTP, no auth tokens needed). Otherwise it falls back to HTTP calls.
"""

import json
import os
import socket
import threading
import wave

import paho.mqtt.client as mqtt
import requests
from dotenv import load_dotenv

load_dotenv()

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


MY_IP = _local_ip()


# ─── HTTP FALLBACK (standalone mode) ──────────────────────────────────────────
def _http_login() -> str:
    res = requests.post(
        f"{API_BASE}/v1/auth/login",
        json={"email": API_EMAIL, "password": API_PASSWORD},
        timeout=10,
    )
    res.raise_for_status()
    token = res.json()["access_token"]
    print(f"[Auth] Logged in as {API_EMAIL}")
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
        print(f"[STT] Failed ({stt_res.status_code}): {stt_res.text}")
        return None

    transcript = stt_res.json().get("text", "").strip()
    conv_id = stt_res.json().get("conv_id")
    print(f"[STT] {transcript!r}")
    if not transcript:
        return None

    ask_res = requests.post(
        f"{API_BASE}/v1/ai/ask",
        json={"question": transcript, "conv_id": conv_id},
        headers=_auth(),
        timeout=60,
    )
    if ask_res.status_code != 200:
        print(f"[ASK] Failed ({ask_res.status_code}): {ask_res.text}")
        return None

    answer = ask_res.json().get("answer", "")
    print(f"[ASK] {answer!r}")

    tts_res = requests.post(
        f"{API_BASE}/v1/ai/tts",
        json={"text": answer, "lang": "hi"},
        headers=_auth(),
        timeout=60,
    )
    if tts_res.status_code != 200:
        print(f"[TTS] Failed ({tts_res.status_code}): {tts_res.text}")
        return None

    return tts_res.json().get("audio_url")


# ─── DIRECT CALL MODE (embedded in Flask process) ─────────────────────────────
def _pipeline_direct(wav_bytes: bytes, flask_app) -> str | None:
    """STT → ASK → TTS by calling the AI functions directly."""
    from app.api.v1.ai import run_stt, run_ask, run_tts

    with flask_app.app_context():
        transcript = run_stt(wav_bytes, lang="hi")
        print(f"[STT] {transcript!r}")
        if not transcript:
            return None

        answer = run_ask(transcript)
        print(f"[ASK] {answer!r}")

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
    print(f"\n[Bridge] Saved {filename} ({len(buffer_data)} bytes)")

    if flask_app is not None:
        audio_url = _pipeline_direct(buffer_data, flask_app)
    else:
        audio_url = _pipeline_http(filename)

    if not audio_url:
        return

    print(f"[MQTT] → ESP32 play: {audio_url}")
    mqtt_client.publish(
        TOPIC_PUB_RESPONSE,
        json.dumps({"identifier": "audioplay", "inputParams": {"url": audio_url}}),
    )


# ─── UDP RECEIVER ─────────────────────────────────────────────────────────────
def _udp_loop(mqtt_client: mqtt.Client, flask_app=None):
    global audio_chunks
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    print(f"[UDP] Listening on {MY_IP}:{UDP_PORT}...")

    while True:
        data, addr = sock.recvfrom(2048)
        try:
            token_len = int.from_bytes(data[0:4], byteorder="big")
            payload = data[4 + token_len:]
            if b"STOP" in payload:
                print(f"\n[UDP] STOP from {addr}")
                if audio_chunks:
                    _handle_audio(b"".join(audio_chunks), mqtt_client, flask_app)
                    audio_chunks = []
            else:
                audio_chunks.append(payload)
                print(f"[UDP] Buffering chunk {len(audio_chunks)}...", end="\r")
        except Exception:
            pass


# ─── MQTT ─────────────────────────────────────────────────────────────────────
def _make_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.tls_set()

    def on_connect(client, _userdata, _flags, _rc, _properties=None):
        print("[MQTT] Connected.")
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
        except Exception:
            pass

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

    print("[Bridge] MQTT + UDP threads started.")


# ─── STANDALONE ENTRY POINT ───────────────────────────────────────────────────
if __name__ == "__main__":
    _http_token = _http_login()
    client = _make_mqtt_client()
    client.connect(MQTT_BROKER, MQTT_PORT)
    threading.Thread(target=client.loop_forever, daemon=True).start()
    _udp_loop(client)  # blocking in main thread
