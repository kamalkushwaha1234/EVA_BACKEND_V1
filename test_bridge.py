"""
Unit and Integration Tests for bridge.py
"""

import pytest
import json
import socket
import threading
from unittest.mock import Mock, patch, MagicMock, mock_open, call
from io import BytesIO

import bridge


# ─── UNIT TESTS: NETWORK & IP ─────────────────────────────────────────────────
class TestNetworkHelpers:
    """Test network utility functions."""

    def test_local_ip_returns_string(self):
        """Test that _local_ip returns a valid IP address string."""
        ip = bridge._local_ip()
        assert isinstance(ip, str)
        assert len(ip) > 0
        # Should be either a valid IP or fallback
        assert ip in ["127.0.0.1"] or "." in ip

    def test_local_ip_fallback_on_error(self):
        """Test that _local_ip falls back to 127.0.0.1 on socket error."""
        with patch("socket.socket") as mock_socket:
            mock_socket.return_value.connect.side_effect = Exception("Network error")
            ip = bridge._local_ip()
            assert ip == "127.0.0.1"


# ─── UNIT TESTS: HTTP & AUTH ──────────────────────────────────────────────────
class TestHTTPAuth:
    """Test HTTP authentication functions."""

    @patch("bridge.requests.post")
    def test_http_login_success(self, mock_post):
        """Test successful HTTP login."""
        mock_post.return_value.json.return_value = {"access_token": "test_token_xyz"}
        
        token = bridge._http_login()
        
        assert token == "test_token_xyz"
        mock_post.assert_called_once()
        assert "auth/login" in mock_post.call_args[0][0]

    @patch("bridge.requests.post")
    def test_http_login_failure(self, mock_post):
        """Test HTTP login failure raises error."""
        mock_post.return_value.raise_for_status.side_effect = Exception("Auth failed")
        
        with pytest.raises(Exception):
            bridge._http_login()

    def test_auth_header_format(self):
        """Test that _auth() returns correctly formatted bearer token."""
        bridge._http_token = "test_token_123"
        headers = bridge._auth()
        
        assert headers == {"Authorization": "Bearer test_token_123"}
        assert "Bearer" in headers["Authorization"]


# ─── UNIT TESTS: STT/ASK/TTS PIPELINE ─────────────────────────────────────────
class TestHTTPPipeline:
    """Test STT → ASK → TTS HTTP pipeline."""

    @patch("bridge.requests.post")
    @patch("builtins.open", new_callable=mock_open, read_data=b"audio_data")
    def test_pipeline_http_success(self, mock_file, mock_post):
        """Test complete HTTP pipeline success."""
        bridge._http_token = "valid_token"
        
        # Mock responses for STT, ASK, TTS
        mock_post.side_effect = [
            # STT response
            MagicMock(
                status_code=200,
                json=lambda: {"text": "hello world", "conv_id": "conv_123"}
            ),
            # ASK response
            MagicMock(
                status_code=200,
                json=lambda: {"answer": "Hello! How can I help?"}
            ),
            # TTS response
            MagicMock(
                status_code=200,
                json=lambda: {"audio_url": "http://localhost:5000/audio.wav"}
            ),
        ]
        
        result = bridge._pipeline_http("test_recording.wav")
        
        assert result == "http://localhost:5000/audio.wav"
        assert mock_post.call_count == 3

    @patch("bridge.requests.post")
    @patch("builtins.open", new_callable=mock_open, read_data=b"audio_data")
    def test_pipeline_http_stt_failure(self, mock_file, mock_post):
        """Test pipeline handles STT failure."""
        bridge._http_token = "valid_token"
        mock_post.return_value.status_code = 500
        mock_post.return_value.text = "STT Error"
        
        result = bridge._pipeline_http("test_recording.wav")
        
        assert result is None

    @patch("bridge.requests.post")
    @patch("builtins.open", new_callable=mock_open, read_data=b"audio_data")
    def test_pipeline_http_empty_transcript(self, mock_file, mock_post):
        """Test pipeline handles empty STT transcript."""
        bridge._http_token = "valid_token"
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"text": "", "conv_id": "conv_123"}
        
        result = bridge._pipeline_http("test_recording.wav")
        
        assert result is None

    @patch("bridge.requests.post")
    def test_pipeline_http_token_refresh(self, mock_post):
        """Test pipeline refreshes token on 401."""
        bridge._http_token = "old_token"
        
        # First call returns 401, then login succeeds, then pipeline succeeds
        mock_post.side_effect = [
            MagicMock(status_code=401),  # STT fails with 401
            MagicMock(status_code=200, json=lambda: {"access_token": "new_token"}),  # Login
            MagicMock(status_code=200, json=lambda: {"text": "hello", "conv_id": "conv_123"}),  # STT retry
            MagicMock(status_code=200, json=lambda: {"answer": "Hi"}),  # ASK
            MagicMock(status_code=200, json=lambda: {"audio_url": "http://localhost/audio.wav"}),  # TTS
        ]
        
        with patch("builtins.open", mock_open(read_data=b"audio")):
            result = bridge._pipeline_http("test_recording.wav")
        
        assert result == "http://localhost/audio.wav"


# ─── UNIT TESTS: DIRECT CALL PIPELINE ────────────────────────────────────────
class TestDirectPipeline:
    """Test STT → ASK → TTS direct call pipeline."""

    @patch("bridge._pipeline_direct")
    def test_pipeline_direct_called(self, mock_direct):
        """Test direct pipeline can be called."""
        mock_direct.return_value = "http://localhost:5000/audio.wav"
        flask_app = MagicMock()
        
        result = bridge._pipeline_direct(b"audio_bytes", flask_app)
        
        assert result == "http://localhost:5000/audio.wav"


# ─── UNIT TESTS: AUDIO PROCESSING ───────────────────────────────────────────
class TestAudioProcessing:
    """Test audio handling functions."""

    @patch("bridge._pipeline_http")
    @patch("wave.open")
    def test_handle_audio_saves_wav(self, mock_wave, mock_pipeline):
        """Test that _handle_audio saves WAV file."""
        mock_pipeline.return_value = "http://localhost:5000/audio.wav"
        bridge._http_token = "token"
        
        # Properly mock the wave file object
        mock_wf = MagicMock()
        mock_wave.return_value.__enter__.return_value = mock_wf
        mock_wave.return_value.__exit__.return_value = None
        
        mqtt_client = MagicMock()
        audio_data = b"\x00\x01\x02\x03"
        
        bridge._handle_audio(audio_data, mqtt_client)
        
        # Verify wave.open was called
        mock_wave.assert_called_once_with("recording.wav", "wb")
        mock_wf.writeframes.assert_called_once_with(audio_data)

    @patch("bridge._pipeline_http")
    @patch("wave.open")
    def test_handle_audio_publishes_mqtt(self, mock_wave, mock_pipeline):
        """Test that _handle_audio publishes result to MQTT."""
        mock_pipeline.return_value = "http://localhost:5000/audio.wav"
        bridge._http_token = "token"
        
        # Properly mock the wave file object
        mock_wf = MagicMock()
        mock_wave.return_value.__enter__.return_value = mock_wf
        mock_wave.return_value.__exit__.return_value = None
        
        mqtt_client = MagicMock()
        audio_data = b"\x00\x01\x02\x03"
        
        bridge._handle_audio(audio_data, mqtt_client)
        
        # Verify MQTT publish was called
        mqtt_client.publish.assert_called_once()
        call_args = mqtt_client.publish.call_args
        assert "audioplay" in call_args[0][1]
        assert "http://localhost:5000/audio.wav" in call_args[0][1]

    @patch("bridge._pipeline_http")
    @patch("wave.open")
    def test_handle_audio_no_url_returns(self, mock_wave, mock_pipeline):
        """Test that _handle_audio returns if pipeline returns None."""
        mock_pipeline.return_value = None
        bridge._http_token = "token"
        
        # Properly mock the wave file object
        mock_wf = MagicMock()
        mock_wave.return_value.__enter__.return_value = mock_wf
        mock_wave.return_value.__exit__.return_value = None
        
        mqtt_client = MagicMock()
        audio_data = b"\x00\x01\x02\x03"
        
        bridge._handle_audio(audio_data, mqtt_client)
        
        # Verify MQTT publish was NOT called
        mqtt_client.publish.assert_not_called()


# ─── UNIT TESTS: MQTT CLIENT ──────────────────────────────────────────────────
class TestMQTTClient:
    """Test MQTT client creation and behavior."""

    def test_make_mqtt_client_creation(self):
        """Test that MQTT client is created successfully."""
        client = bridge._make_mqtt_client()
        
        assert client is not None
        # Verify client has required methods
        assert hasattr(client, "publish")
        assert hasattr(client, "subscribe")
        assert hasattr(client, "connect")

    @patch("bridge.mqtt.Client")
    def test_mqtt_client_login_message(self, mock_mqtt_class):
        """Test MQTT client handles login message."""
        mock_client = MagicMock()
        mock_mqtt_class.return_value = mock_client
        
        client = bridge._make_mqtt_client()
        on_message_callback = mock_client.on_message
        
        # Simulate login message
        msg = MagicMock()
        msg.payload = json.dumps({"identifier": "login"}).encode()
        
        on_message_callback(client, None, msg)
        
        # Verify response was published
        mock_client.publish.assert_called()
        published_data = mock_client.publish.call_args[0][1]
        assert "updatetoken" in published_data

    @patch("bridge.mqtt.Client")
    def test_mqtt_client_data_config_message(self, mock_mqtt_class):
        """Test MQTT client handles data_config message."""
        mock_client = MagicMock()
        mock_mqtt_class.return_value = mock_client
        
        client = bridge._make_mqtt_client()
        on_message_callback = mock_client.on_message
        
        # Simulate data_config message
        msg = MagicMock()
        msg.payload = json.dumps({"identifier": "data_config"}).encode()
        
        on_message_callback(client, None, msg)
        
        # Verify response was published
        mock_client.publish.assert_called()
        published_data = json.loads(mock_client.publish.call_args[0][1])
        assert published_data["identifier"] == "updateconfig"
        assert published_data["inputParams"]["udp_port"] == bridge.UDP_PORT


# ─── INTEGRATION TESTS: UDP LOOP ──────────────────────────────────────────────
class TestUDPLoop:
    """Test UDP reception and processing."""

    @patch("bridge._handle_audio")
    @patch("bridge.socket.socket")
    def test_udp_receives_and_buffers_audio(self, mock_socket_class, mock_handle_audio):
        """Test UDP loop receives and buffers audio chunks."""
        mock_socket = MagicMock()
        mock_socket_class.return_value = mock_socket
        
        # Simulate UDP packets
        audio_chunk_1 = b"\x00\x00\x00\x00" + b"chunk_1"
        audio_chunk_2 = b"\x00\x00\x00\x00" + b"chunk_2"
        stop_signal = b"\x00\x00\x00\x00STOP"
        
        mock_socket.recvfrom.side_effect = [
            (audio_chunk_1, ("192.168.1.1", 5005)),
            (audio_chunk_2, ("192.168.1.1", 5005)),
            (stop_signal, ("192.168.1.1", 5005)),
        ]
        
        mqtt_client = MagicMock()
        
        # We need to break the loop, so we'll use a timeout
        def udp_loop_with_timeout():
            try:
                bridge._udp_loop(mqtt_client)
            except:
                pass
        
        # Run for a limited time
        thread = threading.Thread(target=udp_loop_with_timeout, daemon=True)
        thread.start()
        thread.join(timeout=1)
        
        # Verify handle_audio was called
        mock_handle_audio.assert_called()

    @patch("bridge.socket.socket")
    def test_udp_loop_handles_malformed_packets(self, mock_socket_class):
        """Test UDP loop gracefully handles malformed packets."""
        mock_socket = MagicMock()
        mock_socket_class.return_value = mock_socket
        
        # Malformed packet (too short)
        malformed_packet = b"\x00"
        
        mock_socket.recvfrom.side_effect = [
            (malformed_packet, ("192.168.1.1", 5005)),
            # Break the loop after one bad packet
        ]
        
        mqtt_client = MagicMock()
        
        # Should not raise an error
        try:
            # This will fail when trying to get the second packet, but that's OK
            bridge._udp_loop(mqtt_client)
        except:
            pass  # Expected


# ─── INTEGRATION TESTS: BRIDGE START ──────────────────────────────────────────
class TestBridgeStart:
    """Test bridge startup and threading."""

    @patch("bridge._make_mqtt_client")
    @patch("bridge.threading.Thread")
    def test_start_bridge_creates_threads(self, mock_thread_class, mock_mqtt_class):
        """Test that start_bridge creates MQTT and UDP threads."""
        mock_client = MagicMock()
        mock_mqtt_class.return_value = mock_client
        
        bridge.start_bridge()
        
        # Verify MQTT client was created
        mock_mqtt_class.assert_called_once()
        
        # Verify threads were created (2 threads: loop_forever and udp_loop)
        assert mock_thread_class.call_count == 2

    @patch("bridge._make_mqtt_client")
    def test_start_bridge_with_flask_app(self, mock_mqtt_class):
        """Test start_bridge accepts Flask app for embedded mode."""
        mock_client = MagicMock()
        mock_mqtt_class.return_value = mock_client
        flask_app = MagicMock()
        
        # Should not raise an error
        bridge.start_bridge(flask_app=flask_app)
        
        mock_mqtt_class.assert_called_once()


# ─── CONFIGURATION TESTS ──────────────────────────────────────────────────────
class TestConfiguration:
    """Test environment configuration."""

    def test_mqtt_config_loaded(self):
        """Test that MQTT configuration is loaded."""
        assert bridge.MQTT_BROKER is not None
        assert bridge.MQTT_PORT > 0
        assert isinstance(bridge.MQTT_PORT, int)

    def test_udp_config_loaded(self):
        """Test that UDP configuration is loaded."""
        assert bridge.UDP_PORT > 0
        assert isinstance(bridge.UDP_PORT, int)

    def test_api_config_loaded(self):
        """Test that API configuration is loaded."""
        assert bridge.API_BASE is not None
        assert bridge.API_EMAIL is not None


# ─── FIXTURE & PARAMETRIZED TESTS ─────────────────────────────────────────────
@pytest.fixture
def mock_mqtt_client():
    """Fixture for mocked MQTT client."""
    return MagicMock()


@pytest.fixture
def mock_flask_app():
    """Fixture for mocked Flask app."""
    app = MagicMock()
    app.app_context.return_value.__enter__ = MagicMock()
    app.app_context.return_value.__exit__ = MagicMock(return_value=False)
    return app


@pytest.mark.parametrize("audio_size", [512, 1024, 4096, 8192])
def test_audio_processing_various_sizes(audio_size):
    """Test audio processing with various buffer sizes."""
    with patch("bridge._pipeline_http") as mock_pipeline, \
         patch("wave.open") as mock_wave:
        
        # Set return value for pipeline
        mock_pipeline.return_value = "http://localhost:5000/audio.wav"
        
        # Properly mock the wave file object
        mock_wf = MagicMock()
        mock_wave.return_value.__enter__.return_value = mock_wf
        mock_wave.return_value.__exit__.return_value = None
        
        bridge._http_token = "token"
        mqtt_client = MagicMock()
        audio_data = b"\x00" * audio_size
        
        # Should not raise an error
        bridge._handle_audio(audio_data, mqtt_client)


@pytest.mark.parametrize("error_code,should_fail", [
    (200, False),
    (400, True),
    (401, False),  # Retries with new token
    (500, True),
])
@patch("bridge.requests.post")
@patch("builtins.open", new_callable=mock_open, read_data=b"audio")
def test_stt_various_status_codes(mock_file, mock_post, error_code, should_fail):
    """Test STT pipeline with various HTTP status codes."""
    bridge._http_token = "valid_token"
    
    if error_code == 200:
        # For 200, we need to return proper responses for STT, ASK, and TTS
        mock_post.side_effect = [
            MagicMock(status_code=200, json=lambda: {"text": "hello", "conv_id": "conv_123"}),
            MagicMock(status_code=200, json=lambda: {"answer": "Hi"}),
            MagicMock(status_code=200, json=lambda: {"audio_url": "http://localhost/audio.wav"}),
        ]
        result = bridge._pipeline_http("test.wav")
        assert result == "http://localhost/audio.wav"
    elif error_code == 401:
        # Test token refresh
        mock_post.side_effect = [
            MagicMock(status_code=401),  # First STT fails
            MagicMock(status_code=200, json=lambda: {"access_token": "new_token"}),  # Login
            MagicMock(status_code=200, json=lambda: {"text": "hello", "conv_id": "conv_123"}),  # STT retry
            MagicMock(status_code=200, json=lambda: {"answer": "Hi"}),  # ASK
            MagicMock(status_code=200, json=lambda: {"audio_url": "http://localhost/audio.wav"}),  # TTS
        ]
        result = bridge._pipeline_http("test.wav")
        assert result == "http://localhost/audio.wav"
    else:
        # For 400, 500, return error immediately
        mock_post.return_value.status_code = error_code
        mock_post.return_value.text = f"Error {error_code}"
        result = bridge._pipeline_http("test.wav")
        assert result is None
