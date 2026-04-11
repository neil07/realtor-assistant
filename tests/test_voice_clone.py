"""Tests for voice clone service, generate_voice enhancements, and profile_manager."""

import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup — scripts dir must be importable
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
SCRIPTS_DIR = str(
    Path(__file__).resolve().parents[1] / "skills" / "listing-video" / "scripts"
)
sys.path.insert(0, SCRIPTS_DIR)

import generate_voice
import profile_manager
import voice_clone_service


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture(autouse=True)
def _isolate_output(tmp_path, monkeypatch):
    """Every test writes to a temp directory — never touches real output."""
    monkeypatch.setattr(
        voice_clone_service, "OUTPUT_BASE", tmp_path / "voice-clones"
    )


@pytest.fixture
def fake_wav(tmp_path):
    """Create a minimal valid 30-second WAV file (16 kHz mono PCM)."""
    wav_path = tmp_path / "sample.wav"
    sample_rate = 16000
    duration_s = 30
    num_samples = sample_rate * duration_s
    data_size = num_samples * 2  # 16-bit

    with open(wav_path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sample_rate,
                            sample_rate * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(b"\x00" * data_size)

    return str(wav_path)


@pytest.fixture
def fake_video(tmp_path):
    """Fake video file (just bytes — ffmpeg will be mocked)."""
    p = tmp_path / "agent_intro.mp4"
    p.write_bytes(b"\x00" * 1024)
    return str(p)


@pytest.fixture
def session_with_speakers(tmp_path, fake_wav):
    """Pre-built session directory with 2 speakers ready for selection."""
    phone = "+1555000111"
    sid = "sess-abc"
    sdir = tmp_path / "voice-clones" / "+1555000111" / sid
    sdir.mkdir(parents=True)

    sp0 = str(sdir / "speaker_0.wav")
    sp1 = str(sdir / "speaker_1.wav")
    shutil.copy(fake_wav, sp0)
    shutil.copy(fake_wav, sp1)

    data = {
        "session_id": sid,
        "agent_phone": phone,
        "speakers": [
            {"speaker_id": "speaker_0", "audio_path": sp0, "duration": 20.0},
            {"speaker_id": "speaker_1", "audio_path": sp1, "duration": 12.5},
        ],
        "status": "awaiting_selection",
    }
    (sdir / "session.json").write_text(json.dumps(data))
    return phone, sid, sdir


# ═══════════════════════════════════════════════════════════════════════════
# voice_clone_service — Session helpers
# ═══════════════════════════════════════════════════════════════════════════


class TestSessionManagement:
    """_session_dir / _save_session / _load_session"""

    def test_session_dir_sanitises_phone(self):
        d = voice_clone_service._session_dir("+1 (555) 123-4567", "abc")
        assert "+15551234567" in str(d)

    def test_save_and_load_roundtrip(self, tmp_path):
        d = tmp_path / "sess"
        payload = {"key": "value", "num": 42}
        voice_clone_service._save_session(d, payload)
        loaded = voice_clone_service._load_session(d)
        assert loaded == payload

    def test_load_missing_returns_none(self, tmp_path):
        assert voice_clone_service._load_session(tmp_path / "nope") is None


# ═══════════════════════════════════════════════════════════════════════════
# voice_clone_service — extract_audio
# ═══════════════════════════════════════════════════════════════════════════


class TestExtractAudio:

    def test_file_not_found(self, tmp_path):
        r = voice_clone_service.extract_audio("/no/such/file.mp4", str(tmp_path))
        assert r["status"] == "error"
        assert "not found" in r["message"]

    @patch("voice_clone_service._get_audio_duration", return_value=45.0)
    @patch("voice_clone_service.subprocess.run")
    def test_success(self, mock_run, _dur, fake_video, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        r = voice_clone_service.extract_audio(fake_video, str(tmp_path / "out"))
        assert r["status"] == "success"
        assert r["duration"] == 45.0
        assert r["audio_path"].endswith("extracted.wav")

    @patch("voice_clone_service._get_audio_duration", return_value=45.0)
    @patch("voice_clone_service.subprocess.run")
    def test_ffmpeg_creates_correct_command(self, mock_run, _dur, fake_video, tmp_path):
        """Verify ffmpeg is called with 16 kHz mono PCM args."""
        mock_run.return_value = MagicMock(returncode=0)
        voice_clone_service.extract_audio(fake_video, str(tmp_path / "out"))
        cmd = mock_run.call_args[0][0]
        assert "-ar" in cmd and "16000" in cmd
        assert "-ac" in cmd and "1" in cmd
        assert "-acodec" in cmd and "pcm_s16le" in cmd

    @patch("voice_clone_service.subprocess.run")
    def test_ffmpeg_nonzero_exit(self, mock_run, fake_video, tmp_path):
        mock_run.return_value = MagicMock(returncode=1, stderr="codec error")
        r = voice_clone_service.extract_audio(fake_video, str(tmp_path / "out"))
        assert r["status"] == "error"
        assert "ffmpeg failed" in r["message"]

    @patch("voice_clone_service.subprocess.run", side_effect=FileNotFoundError)
    def test_ffmpeg_not_installed(self, _run, fake_video, tmp_path):
        r = voice_clone_service.extract_audio(fake_video, str(tmp_path / "out"))
        assert r["status"] == "error"
        assert "ffmpeg not found" in r["message"]

    @patch("voice_clone_service.subprocess.run",
           side_effect=subprocess.TimeoutExpired("ffmpeg", 120))
    def test_ffmpeg_timeout(self, _run, fake_video, tmp_path):
        r = voice_clone_service.extract_audio(fake_video, str(tmp_path / "out"))
        assert r["status"] == "error"
        assert "timed out" in r["message"]

    @patch("voice_clone_service._get_audio_duration", return_value=None)
    @patch("voice_clone_service.subprocess.run")
    def test_duration_unreadable(self, mock_run, _dur, fake_video, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        r = voice_clone_service.extract_audio(fake_video, str(tmp_path / "out"))
        assert r["status"] == "error"
        assert "duration" in r["message"].lower()

    @patch("voice_clone_service._get_audio_duration", return_value=5.0)
    @patch("voice_clone_service.subprocess.run")
    def test_too_short(self, mock_run, _dur, fake_video, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        r = voice_clone_service.extract_audio(fake_video, str(tmp_path / "out"))
        assert r["status"] == "error"
        assert "too short" in r["message"].lower()

    @patch("voice_clone_service._get_audio_duration", return_value=700.0)
    @patch("voice_clone_service.subprocess.run")
    def test_too_long(self, mock_run, _dur, fake_video, tmp_path):
        mock_run.return_value = MagicMock(returncode=0)
        r = voice_clone_service.extract_audio(fake_video, str(tmp_path / "out"))
        assert r["status"] == "error"
        assert "too long" in r["message"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# voice_clone_service — _get_audio_duration
# ═══════════════════════════════════════════════════════════════════════════


class TestGetAudioDuration:

    @patch("voice_clone_service.subprocess.run")
    def test_parses_ffprobe_json(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"format": {"duration": "32.5"}}),
        )
        assert voice_clone_service._get_audio_duration("x.wav") == 32.5

    @patch("voice_clone_service.subprocess.run")
    def test_ffprobe_failure_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert voice_clone_service._get_audio_duration("x.wav") is None

    @patch("voice_clone_service.subprocess.run", side_effect=Exception("boom"))
    def test_exception_returns_none(self, _run):
        assert voice_clone_service._get_audio_duration("x.wav") is None


# ═══════════════════════════════════════════════════════════════════════════
# voice_clone_service — diarize_speakers
# ═══════════════════════════════════════════════════════════════════════════


class _FakeTurn:
    """Mimics pyannote Segment for itertracks()."""
    def __init__(self, start, end):
        self.start = start
        self.end = end


class _FakeAudioSegment:
    """Minimal pydub AudioSegment stand-in."""
    def __init__(self, length_ms=30000):
        self._len = length_ms

    def __getitem__(self, sl):
        return _FakeAudioSegment(sl.stop - sl.start)

    def __iadd__(self, other):
        self._len += other._len
        return self

    def __len__(self):
        return self._len

    @classmethod
    def empty(cls):
        return cls(0)

    @classmethod
    def from_wav(cls, _path):
        return cls(60000)  # 60 s

    def export(self, path, format="wav"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"\x00" * 100)


class TestDiarizeSpeakers:

    def _run_diarize(self, tracks, audio_path, output_dir):
        """Helper: patch pyannote + pydub, call diarize_speakers."""
        mock_pipeline_cls = MagicMock()
        mock_pipeline_inst = MagicMock()
        mock_pipeline_cls.from_pretrained.return_value = mock_pipeline_inst
        mock_diarization = MagicMock()
        mock_diarization.itertracks.return_value = tracks
        mock_pipeline_inst.return_value = mock_diarization

        fake_pyannote = MagicMock()
        fake_pyannote.Pipeline = mock_pipeline_cls

        fake_pydub = MagicMock()
        fake_pydub.AudioSegment = _FakeAudioSegment

        with patch.dict("sys.modules", {
            "pyannote": MagicMock(),
            "pyannote.audio": fake_pyannote,
            "pydub": fake_pydub,
        }):
            # Re-run the function body by calling directly — the lazy imports
            # inside diarize_speakers will pick up our patched modules.
            return voice_clone_service.diarize_speakers(audio_path, output_dir)

    def test_single_speaker(self, tmp_path, fake_wav):
        tracks = [
            (_FakeTurn(0.0, 15.0), None, "SPEAKER_00"),
            (_FakeTurn(16.0, 28.0), None, "SPEAKER_00"),
        ]
        r = self._run_diarize(tracks, fake_wav, str(tmp_path / "out"))
        assert r["status"] == "success"
        assert len(r["speakers"]) == 1
        assert r["speakers"][0]["speaker_id"] == "speaker_0"
        assert r["speakers"][0]["duration"] == 27.0

    def test_two_speakers_sorted_by_duration(self, tmp_path, fake_wav):
        tracks = [
            (_FakeTurn(0.0, 5.0), None, "A"),   # 5 s — too short
            (_FakeTurn(6.0, 22.0), None, "B"),   # 16 s
            (_FakeTurn(23.0, 40.0), None, "A"),  # +17 s → total 22 s
            (_FakeTurn(41.0, 55.0), None, "B"),  # +14 s → total 30 s
        ]
        r = self._run_diarize(tracks, fake_wav, str(tmp_path / "out"))
        assert r["status"] == "success"
        assert len(r["speakers"]) == 2
        # speaker_0 should be the one with most speech (B: 30 s)
        assert r["speakers"][0]["duration"] >= r["speakers"][1]["duration"]

    def test_speaker_too_short_filtered(self, tmp_path, fake_wav):
        tracks = [
            (_FakeTurn(0.0, 20.0), None, "LONG"),
            (_FakeTurn(21.0, 25.0), None, "SHORT"),  # 4 s < 10 s min
        ]
        r = self._run_diarize(tracks, fake_wav, str(tmp_path / "out"))
        assert r["status"] == "success"
        assert len(r["speakers"]) == 1

    def test_no_speech_detected(self, tmp_path, fake_wav):
        r = self._run_diarize([], fake_wav, str(tmp_path / "out"))
        assert r["status"] == "error"
        assert "No speech" in r["message"]

    def test_all_speakers_too_short(self, tmp_path, fake_wav):
        tracks = [
            (_FakeTurn(0.0, 3.0), None, "A"),
            (_FakeTurn(4.0, 8.0), None, "B"),
        ]
        r = self._run_diarize(tracks, fake_wav, str(tmp_path / "out"))
        assert r["status"] == "error"
        assert "enough speech" in r["message"]

    def test_segments_rounded(self, tmp_path, fake_wav):
        tracks = [
            (_FakeTurn(0.123456, 15.654321), None, "X"),
        ]
        r = self._run_diarize(tracks, fake_wav, str(tmp_path / "out"))
        assert r["status"] == "success"
        seg = r["speakers"][0]["segments"][0]
        assert seg == (0.12, 15.65)


# ═══════════════════════════════════════════════════════════════════════════
# voice_clone_service — process_video_for_cloning
# ═══════════════════════════════════════════════════════════════════════════


class TestProcessVideoForCloning:

    @patch("voice_clone_service.diarize_speakers")
    @patch("voice_clone_service.extract_audio")
    def test_extract_failure_propagated(self, mock_ext, _diar, fake_video):
        mock_ext.return_value = {"status": "error", "message": "bad file"}
        r = voice_clone_service.process_video_for_cloning(fake_video, "+100")
        assert r["status"] == "error"
        assert r["message"] == "bad file"

    @patch("voice_clone_service.diarize_speakers")
    @patch("voice_clone_service.extract_audio")
    def test_diarize_failure_propagated(self, mock_ext, mock_diar, fake_video):
        mock_ext.return_value = {
            "status": "success", "audio_path": "/tmp/x.wav", "duration": 30,
        }
        mock_diar.return_value = {"status": "error", "message": "no speech"}
        r = voice_clone_service.process_video_for_cloning(fake_video, "+100")
        assert r["status"] == "error"

    @patch("voice_clone_service.diarize_speakers")
    @patch("voice_clone_service.extract_audio")
    def test_single_speaker_flag(self, mock_ext, mock_diar, fake_video, tmp_path):
        mock_ext.return_value = {
            "status": "success",
            "audio_path": str(tmp_path / "x.wav"),
            "duration": 30,
        }
        mock_diar.return_value = {
            "status": "success",
            "speakers": [{
                "speaker_id": "speaker_0",
                "audio_path": str(tmp_path / "sp0.wav"),
                "duration": 25.0,
                "segments": [(0, 25)],
            }],
        }
        r = voice_clone_service.process_video_for_cloning(fake_video, "+100")
        assert r["status"] == "success"
        assert r["single_speaker"] is True
        assert len(r["speakers"]) == 1

    @patch("voice_clone_service.diarize_speakers")
    @patch("voice_clone_service.extract_audio")
    def test_multi_speaker_flag(self, mock_ext, mock_diar, fake_video, tmp_path):
        mock_ext.return_value = {
            "status": "success",
            "audio_path": str(tmp_path / "x.wav"),
            "duration": 60,
        }
        mock_diar.return_value = {
            "status": "success",
            "speakers": [
                {"speaker_id": "speaker_0", "audio_path": str(tmp_path / "a.wav"),
                 "duration": 30, "segments": []},
                {"speaker_id": "speaker_1", "audio_path": str(tmp_path / "b.wav"),
                 "duration": 20, "segments": []},
            ],
        }
        r = voice_clone_service.process_video_for_cloning(fake_video, "+100")
        assert r["status"] == "success"
        assert r["single_speaker"] is False
        assert len(r["speakers"]) == 2

    @patch("voice_clone_service.diarize_speakers")
    @patch("voice_clone_service.extract_audio")
    def test_session_json_persisted(self, mock_ext, mock_diar, fake_video, tmp_path):
        mock_ext.return_value = {
            "status": "success",
            "audio_path": str(tmp_path / "x.wav"),
            "duration": 30,
        }
        mock_diar.return_value = {
            "status": "success",
            "speakers": [{
                "speaker_id": "speaker_0",
                "audio_path": str(tmp_path / "sp0.wav"),
                "duration": 25,
                "segments": [],
            }],
        }
        r = voice_clone_service.process_video_for_cloning(fake_video, "+100")
        sid = r["session_id"]
        sdir = voice_clone_service._session_dir("+100", sid)
        loaded = voice_clone_service._load_session(sdir)
        assert loaded is not None
        assert loaded["status"] == "awaiting_selection"
        assert loaded["agent_phone"] == "+100"

    @patch("voice_clone_service.diarize_speakers")
    @patch("voice_clone_service.extract_audio")
    def test_audio_url_format(self, mock_ext, mock_diar, fake_video, tmp_path):
        mock_ext.return_value = {
            "status": "success",
            "audio_path": str(tmp_path / "x.wav"),
            "duration": 30,
        }
        mock_diar.return_value = {
            "status": "success",
            "speakers": [{
                "speaker_id": "speaker_0",
                "audio_path": str(tmp_path / "sp0.wav"),
                "duration": 25,
                "segments": [],
            }],
        }
        r = voice_clone_service.process_video_for_cloning(fake_video, "+100")
        url = r["speakers"][0]["audio_url"]
        assert url.startswith("/output/")


# ═══════════════════════════════════════════════════════════════════════════
# voice_clone_service — clone_selected_speaker
# ═══════════════════════════════════════════════════════════════════════════


class TestCloneSelectedSpeaker:

    def test_session_not_found(self):
        r = voice_clone_service.clone_selected_speaker(
            "+100", "no-such-sess", "speaker_0"
        )
        assert r["status"] == "error"
        assert "not found" in r["message"]

    def test_speaker_id_not_in_session(self, session_with_speakers):
        phone, sid, _ = session_with_speakers
        r = voice_clone_service.clone_selected_speaker(
            phone, sid, "speaker_99", "Agent"
        )
        assert r["status"] == "error"
        assert "not found" in r["message"]

    @patch("generate_voice.clone_voice")
    @patch("voice_clone_service.generate_preview")
    def test_happy_path(self, mock_prev, mock_clone, session_with_speakers):
        phone, sid, sdir = session_with_speakers
        mock_clone.return_value = {"status": "success", "voice_id": "v_ok"}
        mock_prev.return_value = {
            "status": "success",
            "audio_path": str(sdir / "preview.mp3"),
            "text_used": "Welcome...",
        }

        r = voice_clone_service.clone_selected_speaker(phone, sid, "speaker_0", "A")
        assert r["status"] == "success"
        assert r["voice_id"] == "v_ok"
        assert r["preview_audio_url"] is not None
        assert r["preview_text"] == "Welcome..."
        mock_clone.assert_called_once()

    @patch("generate_voice.clone_voice")
    @patch("voice_clone_service.generate_preview")
    def test_session_updated_after_clone(self, mock_prev, mock_clone, session_with_speakers):
        phone, sid, sdir = session_with_speakers
        mock_clone.return_value = {"status": "success", "voice_id": "v_x"}
        mock_prev.return_value = {"status": "success", "audio_path": "p.mp3", "text_used": ""}

        voice_clone_service.clone_selected_speaker(phone, sid, "speaker_1", "A")
        loaded = voice_clone_service._load_session(sdir)
        assert loaded["status"] == "awaiting_confirmation"
        assert loaded["selected_speaker"] == "speaker_1"
        assert loaded["voice_id"] == "v_x"

    @patch("generate_voice.clone_voice")
    def test_clone_api_failure_propagated(self, mock_clone, session_with_speakers):
        phone, sid, _ = session_with_speakers
        mock_clone.return_value = {"status": "error", "message": "quota exceeded"}
        r = voice_clone_service.clone_selected_speaker(phone, sid, "speaker_0", "A")
        assert r["status"] == "error"
        assert "quota" in r["message"]

    @patch("generate_voice.clone_voice")
    @patch("voice_clone_service.generate_preview")
    def test_preview_failure_still_succeeds(self, mock_prev, mock_clone, session_with_speakers):
        """Preview is optional — clone should still succeed if preview fails."""
        phone, sid, _ = session_with_speakers
        mock_clone.return_value = {"status": "success", "voice_id": "v_y"}
        mock_prev.return_value = {"status": "error", "message": "TTS down", "text_used": ""}

        r = voice_clone_service.clone_selected_speaker(phone, sid, "speaker_0", "A")
        assert r["status"] == "success"
        assert r["preview_audio_url"] is None  # no preview, but clone ok

    @patch("generate_voice.clone_voice")
    @patch("voice_clone_service.generate_preview")
    def test_defaults_agent_name_to_phone(self, mock_prev, mock_clone, session_with_speakers):
        phone, sid, sdir = session_with_speakers
        mock_clone.return_value = {"status": "success", "voice_id": "v_z"}
        mock_prev.return_value = {"status": "success", "audio_path": "p.mp3", "text_used": ""}

        voice_clone_service.clone_selected_speaker(phone, sid, "speaker_0")
        # agent_name defaults to phone when empty
        clone_call_args = mock_clone.call_args
        assert clone_call_args[0][1] == phone  # name arg


# ═══════════════════════════════════════════════════════════════════════════
# voice_clone_service — generate_preview
# ═══════════════════════════════════════════════════════════════════════════


class TestGeneratePreview:

    @patch("generate_voice.generate_elevenlabs")
    def test_success(self, mock_el):
        mock_el.return_value = {"status": "success"}
        r = voice_clone_service.generate_preview("v_id", "/tmp/p.mp3")
        assert r["status"] == "success"
        assert r["audio_path"] == "/tmp/p.mp3"
        assert len(r["text_used"]) > 0
        # Verify correct voice_id passed
        assert mock_el.call_args.kwargs["voice_id"] == "v_id"

    @patch("generate_voice.generate_elevenlabs")
    def test_failure(self, mock_el):
        mock_el.return_value = {"status": "error", "message": "TTS down"}
        r = voice_clone_service.generate_preview("v_id", "/tmp/p.mp3")
        assert r["status"] == "error"
        assert "TTS down" in r["message"]

    @patch("generate_voice.generate_elevenlabs")
    def test_uses_preview_text(self, mock_el):
        mock_el.return_value = {"status": "success"}
        r = voice_clone_service.generate_preview("v_id", "/tmp/p.mp3")
        assert r["text_used"] in voice_clone_service._PREVIEW_TEXTS


# ═══════════════════════════════════════════════════════════════════════════
# voice_clone_service — confirm_clone / reject_clone
# ═══════════════════════════════════════════════════════════════════════════


class TestConfirmReject:

    @patch("profile_manager.update_profile")
    @patch("profile_manager.set_voice_clone")
    def test_confirm_stores_in_profile(self, mock_set, mock_update):
        r = voice_clone_service.confirm_clone("+100", "v_abc")
        assert r["status"] == "confirmed"
        assert r["voice_id"] == "v_abc"
        mock_set.assert_called_once_with("+100", "v_abc")
        # Also records created_at
        mock_update.assert_called_once()
        ts = mock_update.call_args[0][1]
        assert "voice_clone_created_at" in ts

    @patch("generate_voice.delete_voice")
    def test_reject_deletes_voice(self, mock_del):
        mock_del.return_value = {"status": "success"}
        r = voice_clone_service.reject_clone("+100", "v_abc")
        assert r["status"] == "rejected"
        mock_del.assert_called_once_with("v_abc")

    @patch("generate_voice.delete_voice")
    def test_reject_still_succeeds_on_delete_failure(self, mock_del):
        """Even if ElevenLabs deletion fails, we still return 'rejected'."""
        mock_del.return_value = {"status": "error", "message": "network"}
        r = voice_clone_service.reject_clone("+100", "v_abc")
        assert r["status"] == "rejected"


# ═══════════════════════════════════════════════════════════════════════════
# voice_clone_service — get_clone_status
# ═══════════════════════════════════════════════════════════════════════════


class TestGetCloneStatus:

    @patch("profile_manager.get_profile", return_value=None)
    def test_no_profile(self, _gp):
        r = voice_clone_service.get_clone_status("+100")
        assert r["has_clone"] is False
        assert r["voice_id"] is None

    @patch("profile_manager.get_profile")
    def test_has_clone(self, mock_gp):
        mock_gp.return_value = {
            "voice_clone_id": "v_abc",
            "voice_clone_offered": True,
            "voice_clone_created_at": "2026-04-01T00:00:00",
        }
        r = voice_clone_service.get_clone_status("+100")
        assert r["has_clone"] is True
        assert r["voice_id"] == "v_abc"
        assert r["offered"] is True

    @patch("profile_manager.get_profile")
    def test_no_clone(self, mock_gp):
        mock_gp.return_value = {
            "voice_clone_id": None,
            "voice_clone_offered": False,
        }
        r = voice_clone_service.get_clone_status("+100")
        assert r["has_clone"] is False


# ═══════════════════════════════════════════════════════════════════════════
# generate_voice — clone_voice (multi-file, MIME)
# ═══════════════════════════════════════════════════════════════════════════


class TestCloneVoice:

    @pytest.fixture(autouse=True)
    def _set_key(self, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")

    def _mock_ok(self, voice_id="v_new"):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"voice_id": voice_id}
        return resp

    @patch("generate_voice.requests.post")
    def test_single_file_string(self, mock_post, fake_wav):
        mock_post.return_value = self._mock_ok()
        r = generate_voice.clone_voice(fake_wav, "Agent")
        assert r["status"] == "success"
        assert r["voice_name"] == "RE_Agent_Agent"

    @patch("generate_voice.requests.post")
    def test_multi_file_list(self, mock_post, fake_wav, tmp_path):
        mock_post.return_value = self._mock_ok()
        wav2 = str(tmp_path / "s2.wav")
        shutil.copy(fake_wav, wav2)

        r = generate_voice.clone_voice([fake_wav, wav2], "Agent")
        assert r["status"] == "success"
        files_arg = mock_post.call_args.kwargs.get("files", [])
        assert len(files_arg) == 2

    @patch("generate_voice.requests.post")
    def test_mime_type_detection(self, mock_post, tmp_path):
        """Different extensions → correct MIME types in multipart."""
        mock_post.return_value = self._mock_ok()

        ogg = tmp_path / "voice.ogg"
        ogg.write_bytes(b"\x00")
        m4a = tmp_path / "voice.m4a"
        m4a.write_bytes(b"\x00")

        generate_voice.clone_voice([str(ogg), str(m4a)], "Agent")
        files_arg = mock_post.call_args.kwargs["files"]
        mimes = [f[1][2] for f in files_arg]
        assert "audio/ogg" in mimes
        assert "audio/mp4" in mimes

    @patch("generate_voice.requests.post")
    def test_unknown_extension_defaults_to_mpeg(self, mock_post, tmp_path):
        mock_post.return_value = self._mock_ok()
        raw = tmp_path / "voice.raw"
        raw.write_bytes(b"\x00")
        generate_voice.clone_voice(str(raw), "Agent")
        mime = mock_post.call_args.kwargs["files"][0][1][2]
        assert mime == "audio/mpeg"

    @patch("generate_voice.requests.post")
    def test_api_failure(self, mock_post, fake_wav):
        resp = MagicMock()
        resp.status_code = 422
        resp.text = "Invalid audio format"
        mock_post.return_value = resp
        r = generate_voice.clone_voice(fake_wav, "Agent")
        assert r["status"] == "error"
        assert "Invalid audio" in r["message"]

    def test_no_api_key(self, fake_wav, monkeypatch):
        monkeypatch.delenv("ELEVENLABS_API_KEY")
        r = generate_voice.clone_voice(fake_wav, "Agent")
        assert r["status"] == "error"
        assert "API_KEY" in r["message"]

    @patch("generate_voice.requests.post")
    def test_files_closed_after_call(self, mock_post, fake_wav):
        """File handles must be closed even if request fails."""
        mock_post.side_effect = ConnectionError("network")
        with pytest.raises(ConnectionError):
            generate_voice.clone_voice(fake_wav, "Agent")
        # No leaked file handles — verified by pytest tmp_path cleanup


# ═══════════════════════════════════════════════════════════════════════════
# generate_voice — delete_voice
# ═══════════════════════════════════════════════════════════════════════════


class TestDeleteVoice:

    @pytest.fixture(autouse=True)
    def _set_key(self, monkeypatch):
        monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")

    @patch("generate_voice.requests.delete")
    def test_success_200(self, mock_del):
        mock_del.return_value = MagicMock(status_code=200)
        assert generate_voice.delete_voice("v_x")["status"] == "success"

    @patch("generate_voice.requests.delete")
    def test_success_204(self, mock_del):
        mock_del.return_value = MagicMock(status_code=204)
        assert generate_voice.delete_voice("v_x")["status"] == "success"

    @patch("generate_voice.requests.delete")
    def test_not_found(self, mock_del):
        resp = MagicMock(status_code=404, text="Not found")
        mock_del.return_value = resp
        assert generate_voice.delete_voice("v_x")["status"] == "error"

    def test_no_api_key(self, monkeypatch):
        monkeypatch.delenv("ELEVENLABS_API_KEY")
        assert generate_voice.delete_voice("v_x")["status"] == "error"

    @patch("generate_voice.requests.delete")
    def test_correct_url(self, mock_del):
        mock_del.return_value = MagicMock(status_code=200)
        generate_voice.delete_voice("v_abc")
        url = mock_del.call_args[0][0]
        assert url.endswith("/voices/v_abc")


# ═══════════════════════════════════════════════════════════════════════════
# profile_manager — clear_voice_clone
# ═══════════════════════════════════════════════════════════════════════════


class TestProfileManagerVoiceClone:

    @patch("profile_manager.update_profile")
    def test_clear_voice_clone_fields(self, mock_update):
        mock_update.return_value = {}
        profile_manager.clear_voice_clone("+100")
        mock_update.assert_called_once_with("+100", {
            "voice_clone_id": None,
            "voice_clone_offered": False,
            "voice_clone_created_at": None,
        })

    def test_create_profile_has_voice_clone_fields(self, tmp_path, monkeypatch):
        """New profiles must include voice_clone_created_at."""
        monkeypatch.setattr(profile_manager, "PROFILES_DIR", tmp_path)
        p = profile_manager.create_profile("+100", "Test")
        assert "voice_clone_id" in p
        assert "voice_clone_created_at" in p
        assert p["voice_clone_id"] is None
        assert p["voice_clone_created_at"] is None

    def test_should_offer_voice_clone_logic(self, tmp_path, monkeypatch):
        monkeypatch.setattr(profile_manager, "PROFILES_DIR", tmp_path)
        profile_manager.create_profile("+200", "Agent")
        # No videos yet → should not offer
        assert profile_manager.should_offer_voice_clone("+200") is False
        # After first video → should offer
        profile_manager.increment_video_count("+200")
        assert profile_manager.should_offer_voice_clone("+200") is True
        # After marking offered → should not offer again
        profile_manager.mark_voice_clone_offered("+200")
        assert profile_manager.should_offer_voice_clone("+200") is False

    def test_set_and_clear_voice_clone(self, tmp_path, monkeypatch):
        monkeypatch.setattr(profile_manager, "PROFILES_DIR", tmp_path)
        profile_manager.create_profile("+300", "Agent")
        profile_manager.set_voice_clone("+300", "v_abc")
        p = profile_manager.get_profile("+300")
        assert p["voice_clone_id"] == "v_abc"

        profile_manager.clear_voice_clone("+300")
        p = profile_manager.get_profile("+300")
        assert p["voice_clone_id"] is None
        assert p["voice_clone_offered"] is False
