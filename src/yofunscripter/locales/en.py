"""English catalog of the interface texts."""

TEXTS = {
    "app_title": "yoFunscripter",
    "tab_main": "Main",
    "tab_settings": "Settings",

    # The three stages of the window, each card with its folders and its button.
    "stage_scenes": "Cut scenes",
    "stage_scenes_hint": "Videos are cut into scenes by PySceneDetect and ffmpeg "
                         "(frame-accurate trim), one ffmpeg pass per video. Every clip is "
                         "normalized here, once: fps, size, audio.",
    "stage_scripts": "Generate funscripts",
    "stage_scripts_hint": "Each clip is tracked by YOLO and a `.funscript` sidecar is "
                          "written for it, next to the model of the settings.",
    "stage_merge": "Merge",
    "stage_merge_hint": "Selected clips are encoded to one format, concatenated without "
                         "Selected clips are read in place and concatenated with `-c copy`: no re-encoding, no copies — the clips are already normalized at the cut — and one merged funscript is written.",

    "label_source_videos": "Source videos",
    "label_scenes_out": "Scenes folder",
    "label_clips": "Clips folder",
    "label_scripts": "Sidecars folder",
    "label_result_dir": "Result folder",
    "browse": "Browse…",
    "open_folder": "Open",
    "start": "Start",
    "cancel": "Cancel",
    "running": "Running…",

    "min_waves": "Min waves (0 = no filter)",
    "max_waves": "Max waves (0 = no limit)",
    "sort_mode": "Order of clips",
    "result_name": "Result name",
    "pattern_clips": "Clip pattern",
    "sort_tick_rate": "By ticks per second (ascending)",
    "sort_waves_asc": "By waves, ascending",
    "sort_waves_desc": "By waves, descending",
    "sort_keep": "Keep the order of names",
    "sort_random": "Random order",

    # Settings tab.
    "language": "Language",
    "theme": "Color scheme",
    "theme_neon": "Neon",
    "theme_cartoons": "Cartoons",
    "theme_pink": "Pink",
    "jobs": "ffmpeg jobs (stage 1)",
    "threads": "torch threads (stage 2)",
    "device": "Device for YOLO",
    "device_auto": "Auto (GPU if there is one)",
    "device_cpu": "CPU",
    "device_cuda": "CUDA",
    "model": "YOLO model",
    "model_default": "Default: {path}",
    "model_reset": "Reset to the default model",
    "model_bundled": "bundled default",
    "force": "Regenerate sidecars and re-encode segments",
    "no_check": "Skip the checks of the result",
    "apply": "Apply",

    # The progress bar: percent of the real work, ETA, elapsed.
    "progress_idle": "Idle",
    "progress_units": "units",
    "unit_seconds": "s of video",
    "unit_frames": "frames",
    "eta": "{pct}% · {done} / {total} · ETA {eta} · elapsed {elapsed}",

    "console": "Console",
    "clear": "Clear",

    # One line of the stage in the console.
    "stage_start": "▶ {stage}: {source} → {out}",
    "stage_done": "✔ {stage}: done in {elapsed} → {out}",
    "stage_failed": "✖ {stage}: {reason}",
    "stage_cancelled": "⛔ {stage}: stopped by the user",

    # Messages of the window.
    "pick_source_first": "Pick the folder of the source videos first.",
    "no_videos": "No videos in {dir} ({pattern}).",
    "no_clips": "No clips in {dir} ({pattern}).",
    "no_sidecars": "No sidecars in {dir}: run stage 2 first.",
    "model_missing": "Model {path} not found: pick the model in the settings.",
    "locked_output": "{path} is locked by another process (player): close it and run again.",
    "one_stage": "A stage is already running: wait for it to finish.",
    "pick_folder": "Choose the folder",
    "settings_save": "Save",
    "settings_revert": "Revert",
    "settings_restart": "Restart",
    "settings_saved": "Settings are saved.",
    "restart_needed": "Settings are saved: a restart applies the language and the theme.",

    # Check for updates.
    "check_updates": "Check for updates",
    "checking": "Checking…",
    "up_to_date": "Current version {version} is the latest release.",
    "new_version": "A new release {version} is available ({date}).",
    "download": "Download {file}",
    "downloading": "Downloading {file}…",
    "downloaded": "{file} is saved to {dir}",
    "update_failed": "Update check failed: {reason}",
    "no_release": "The repository has no release yet.",
    "updates_title": "Updates",
    "close": "Close",
    "cancel": "Cancel",
    "install_now": "Run the installer",
    "update_ready": "{file} is downloaded and verified.",
    "sha_mismatch": "The downloaded file does not match the published SHA-256.",
    "notes": "Release notes",
}
