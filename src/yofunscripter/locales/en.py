"""English catalog of the interface texts."""

TEXTS = {
    "app_title": "yoFunscripter",
    "tab_main": "Main",
    "tab_settings": "Settings",

    # The three stages of the window, each card with its folders and its button.
    "stage_scenes": "Cut scenes",
    "stage_scenes_hint": "A movie is cut into scenes, one file per scene. Every clip is "
                          "written in one format (30 fps, size, audio), so the clips can be "
                          "merged without re-encoding.",
    "stage_scripts": "Generate funscripts",
    "stage_scripts_hint": "For every clip the movement track is computed — the `.funscript` "
                          "file. It is named like the clip and lives in its own folder.",
    "stage_merge": "Merge",
    "stage_merge_hint": "The chosen clips are joined into one movie and one `.funscript` "
                         "track. Nothing is re-encoded: the clips are read as they are, so "
                         "the merge takes seconds.",

    "label_source_videos": "Source videos",
    "label_scenes_out": "Scenes folder",
    "label_clips": "Clips folder",
    "label_scripts": "Funscript files folder",
    "label_result_dir": "Result folder",
    "browse": "Browse…",
    "open_folder": "Open",
    "start": "Start",
    "cancel": "Cancel",
    "running": "Running…",

    # Tooltips: every line of the window explains itself, no jargon.
    "stage_scenes_tip": "Stage 1. The movie is cut into scenes here, and every scene is "
                        "written in one format. Clips are not reformatted later.",
    "stage_scripts_tip": "Stage 2. YOLO follows the movement in a clip and writes the "
                        ".funscript file — the movement track of the device. One file per "
                        "clip, the file name = the clip name.",
    "stage_merge_tip": "Stage 3. The clips are stacked into one movie and the tracks are "
                       "joined into one. Nothing is re-encoded, so the clips must come from "
                       "one cut, and the .funscript files must be newer than the clips.",
    "label_source_videos_tip": "The folder of the movies the scenes are cut from. It must be "
                               "picked — there is no default.",
    "label_scenes_out_tip": "Where the cut clips are written. Default: ./scenes next to the program.",
    "label_clips_tip": "The folder where the cut clips live. Stages 2 and 3 read clips from here.",
    "label_scripts_tip": "The folder where the .funscript files live — one per clip, with the "
                         "same name as the clip (clip input-s002.mp4 → track input-s002.funscript).",
    "label_result_dir_tip": "Where the merged movie and its track are written. Default: ./result.",
    "browse_tip": "Pick a folder in the file manager.",
    "open_folder_tip": "Open this folder in the file manager; an empty folder is created.",
    "start_tip": "Start this stage.",
    "cancel_tip": "Stop the stage that is running.",

    "min_waves": "Min waves (0 = no filter)",
    "max_waves": "Max waves (0 = no limit)",
    "sort_mode": "Order of clips",
    "result_name": "Result name",
    "pattern_clips": "Clip pattern",
    "min_waves_tip": "A wave is one full cycle of the device (0 → 100 → 0). Clips with fewer "
                     "waves are not taken into the merge. 0 = take every clip.",
    "max_waves_tip": "Clips with more waves than this are not taken into the merge. "
                     "0 = no upper limit.",
    "sort_mode_tip": "Order of the clips in the merged movie. Each mode has its own tooltip.",
    "result_name_tip": "Names of the finished files: {name}.mp4 and {name}.funscript.",
    "pattern_clips_tip": "Which files count as clips, for example *.mp4.",
    "sort_tick_rate": "By ticks per second (ascending)",
    "sort_waves_asc": "By waves, ascending",
    "sort_waves_desc": "By waves, descending",
    "sort_keep": "Keep the order of names",
    "sort_random": "Random order",
    "sort_tick_rate_tip": "Density of movement (ticks per second), from calm clips to active ones.",
    "sort_waves_asc_tip": "Number of waves, ascending: calm clips first.",
    "sort_waves_desc_tip": "Number of waves, descending: active clips first.",
    "sort_keep_tip": "Order of the file names: input-s001, input-s002, …",
    "sort_random_tip": "Shuffled; every run gives a different order.",

    # Settings tab.
    "language": "Language",
    "theme": "Color scheme",
    "theme_neon": "Neon",
    "theme_cartoons": "Cartoons",
    "theme_pink": "Pink",
    "jobs": "Movies cut at once (stage 1)",
    "threads": "YOLO threads (stage 2)",
    "device": "Device for YOLO",
    "device_auto": "Auto (GPU if there is one)",
    "device_cpu": "CPU",
    "device_cuda": "CUDA",
    "model": "YOLO model",
    "model_default": "Default: {path}",
    "model_reset": "Reset to the default model",
    "model_bundled": "bundled default",
    "force": "Do it again: cut the scenes and compute the .funscript files",
    "no_check": "Skip the checks of the result",
    "apply": "Apply",
    "jobs_tip": "How many movies are cut into scenes at the same time. 1 = one after "
                "another: steadier and less load; more = faster, but more memory and disk.",
    "threads_tip": "How many CPU cores one track computation gets. 1 = less load, the same "
                   "result on any machine.",
    "device_tip": "Where YOLO computes the movement track. Auto = GPU when there is one; "
                  "CPU = only the processor; CUDA = require the GPU.",
    "model_tip": "The YOLO weights file (.pt) used for the track. An empty field = the model "
                 "of the build, the same as in yolo.",
    "force_tip": "Finished files are ignored: the scenes are cut again and the .funscript "
                 "files are recomputed. Needed when the clips changed.",
    "no_check_tip": "The merged movie and track are not checked after writing. The check "
                     "catches a track that is out of sync with the video, so keep it on.",
    "settings_save_tip": "Write the values to the settings file. Nothing is applied until the "
                         "button is pressed.",
    "settings_revert_tip": "Return the values that are saved in the settings.",
    "settings_restart_tip": "Start a new copy of the program: the language is applied at start.",
    "language_tip": "Language of the interface, applied after a restart.",
    "theme_tip": "Color scheme of the window, applied right after «Save».",

    # The progress bar: percent of the real work, ETA, elapsed.
    "progress_idle": "Idle",
    "progress_units": "units",
    "unit_seconds": "s of video",
    "unit_frames": "frames",
    "eta": "{pct}% · {done} / {total} · ETA {eta} · elapsed {elapsed}",
    "progress_tip": "Percent of the real work of the stage: seconds of video at the cut, "
                    "frames at the track, seconds at the merge. The estimate comes from the "
                    "speed of this run, not from a guess.",

    "console": "Console",
    "clear": "Clear",
    "clear_tip": "Remove the lines from the screen; the files of the run are not touched.",
    "console_tip": "Every line of a stage is written here: what was computed, what was "
                   "skipped and why.",

    # One line of the stage in the console.
    "stage_start": "▶ {stage}: {source} → {out}",
    "stage_done": "✔ {stage}: done in {elapsed} → {out}",
    "stage_failed": "✖ {stage}: {reason}",
    "stage_cancelled": "⛔ {stage}: stopped by the user",

    # Messages of the window.
    "pick_source_first": "Pick the folder of the source videos first.",
    "no_videos": "No videos in {dir} ({pattern}): pick the source folder in the first card.",
    "no_clips": "No clips in {dir} ({pattern}): run stage 1 first.",
    "merge_no_clips": "No clips in {dir} ({pattern}): run stage 1 first.",
    "merge_no_scripts": "No track can be used: {clips} clips, {missing} .funscript files "
                        "missing in {dir}, {stale} older than the clip. Compute the tracks in "
                        "stage 2 (the .funscript files must be newer than the clips).",
    "merge_none_selected": "Nothing is selected: {clips} clips, «Min waves» = {min_waves}. "
                            "Lower the threshold, or take clips without waves (0).",
    "merge_format": "{count} clips do not fit a merge without re-encoding. The clips must be "
                    "cut in one format — cut them again in stage 1: {list}",
    "merge_locked": "{path} is locked by another process (player): close it and run again.",
    "merge_selected": "Selected {kept} of {rows} clips (min waves {min_waves}, order "
                      "{sort}): {names}",
    "merge_summary": "{name}: {ticks} ticks, {final_ms} ms, {rate} ticks/s, waves {waves} "
                     "({wave_rate} waves/s), {elapsed} s → {out}",
    "scripts_missing": "{clip}: no .funscript file in {dir}",
    "scripts_stale": "{clip}: the .funscript file ({when}) is older than the clip "
                     "({clip_when}) — recompute the track in stage 2",
    "model_missing": "Model {path} not found: pick the model in the settings.",

    # The console lines of the stages, in the language of the window.
    "status_cut": "cut",
    "status_single": "one scene",
    "status_skip": "skipped",
    "status_error": "error",
    "cut_cpu": "Cutting runs on the processor.",
    "cut_gpu": "Cutting runs on the video card.",
    "nvenc_limit": "The video card cannot take {scenes} scenes at once (limit {limit}): "
                   "this clip is cut by the processor.",
    "nvenc_fail": "The video card refused ({text}): this clip is cut by the processor.",
    "stage1_video": "[{done}/{total}] {name}: {status}, {scenes} scenes, {files} files, "
                    "detect {detect} s, cut {cut} s{reason}",
    "stage1_collisions": "{count} videos in {dir} share one name: rename them so every clip "
                         "has its own name: {list}",
    "stage1_summary": "Videos {videos}: cut {cut}, one scene {single}, skipped {skipped}, "
                      "errors {errors}, files {files}, {elapsed} s → {out}",
    "stage2_start": "Clips {clips}, to compute {todo}, model {name} ({version})",
    "stage2_skip": "[{i}/{total}] {name}: skipped — the .funscript file is current",
    "stage2_clip": "[{i}/{total}] {name}: {ticks} ticks, {elapsed} s{reason}",
    "stage2_error": "[{i}/{total}] {name}: error — {reason}",
    "stage2_summary": "Clips {clips}: written {done}, no movement {empty}, skipped {skipped}, "
                      "errors {errors}, {elapsed} s → {out}",
    "cuda_missing": "This build has no CUDA: the generation runs on the processor.",
    "check_summary": "Checks: {passed} of {total} passed.",
    "check_fail_line": "Check failed: {line}",
    "one_stage": "A stage is already running: wait for it to finish.",
    "pick_folder": "Choose the folder",
    "settings_save": "Save",
    "settings_revert": "Revert",
    "settings_restart": "Restart",
    "settings_saved": "Settings are saved.",
    "restart_needed": "Settings are saved: a restart applies the language and the theme.",

    # Check for updates.
    "check_updates": "Check for updates",
    "check_updates_tip": "Look at the releases of the repository: a new version is "
                         "downloaded from GitHub and installed by its own installer.",
    "checking": "Checking…",
    "up_to_date": "Current version {version} is the latest release.",
    "new_version": "A new release {version} is available ({date}).",
    "update_ready_to": "{file} is not downloaded yet.",
    "update_now": "Update",
    "downloading": "Downloading {file}…",
    "update_stopping": "Stopping the download…",
    "installing": "Starting the installer {file}…",
    "update_stopped": "{file}: the download is stopped by the user.",
    "update_failed": "Update check failed: {reason}",
    "no_release": "The repository has no release yet.",
    "updates_title": "Updates",
    "close": "Close",
    "cancel": "Cancel",
    "sha_mismatch": "The downloaded file does not match the published SHA-256.",
    "notes": "Release notes",
}
