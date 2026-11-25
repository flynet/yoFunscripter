"""Settings: defaults, clamping of bad values, the backup of a damaged file, atomic save."""

from __future__ import annotations

import json

from yofunscripter.config.settings import Settings, load_settings, save_settings


def test_defaults(tmp_path):
    s = load_settings(tmp_path / "settings.json")
    assert s.language == "en"
    assert s.theme == "neon"
    assert s.device == "auto"
    assert s.jobs == 1 and s.threads == 1
    assert s.min_waves == 3 and s.max_waves == 0
    assert s.sort_mode == "tick_rate"
    assert s.model_path == ""
    assert s.scenes_in == ""


def test_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    s = Settings(language="ru", theme="pink", jobs=4, threads=8, device="cuda",
                 min_waves=5, sort_mode="waves_desc", scenes_out="D:/clips",
                 result_name="final")
    save_settings(s, path)
    loaded = load_settings(path)
    assert loaded == s
    assert not (tmp_path / "settings.json.new").exists()


def test_invalid_values_fall_back(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "language": "de", "theme": "sepia", "device": "tpu",
        "jobs": 0, "threads": 999, "min_waves": -4, "max_waves": -1,
        "sort_mode": "shuffle", "result_name": "   ",
        "pattern_scenes": "mp4", "pattern_clips": "",
        "unknown_key": 1,
    }), encoding="utf-8")
    s = load_settings(path)
    assert s.language == "en"
    assert s.theme == "neon"
    assert s.device == "auto"
    assert s.jobs == 1
    assert s.threads == 64
    assert s.min_waves == 0 and s.max_waves == 0
    assert s.sort_mode == "tick_rate"
    assert s.result_name == "result"
    assert s.pattern_scenes == "*.mp4" and s.pattern_clips == "*.mp4"


def test_first_save_has_no_backup(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(jobs=2), path)
    assert not (tmp_path / "settings.json.bak").exists()


def test_damaged_file_reads_the_previous_save(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(jobs=2, theme="pink"), path)
    # the second save keeps the file of the first save as settings.json.bak
    save_settings(Settings(jobs=7, theme="pink"), path)
    path.write_text("{ not json", encoding="utf-8")
    s = load_settings(path)
    assert s.jobs == 2 and s.theme == "pink"


def test_backup_survives_a_missing_file(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(Settings(jobs=3), path)
    save_settings(Settings(jobs=7), path)
    path.unlink()
    s = load_settings(path)
    assert s.jobs == 3


def test_wrong_type_is_ignored(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"jobs": "many", "theme": "neon"}), encoding="utf-8")
    s = load_settings(path)
    assert s.jobs == 1 and s.theme == "neon"
