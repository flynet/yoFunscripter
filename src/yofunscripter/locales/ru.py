"""Русский каталог текстов интерфейса."""

TEXTS = {
    "app_title": "yoFunscripter",
    "tab_main": "Главная",
    "tab_settings": "Настройки",

    # Три стадии окна: у каждой свои папки и своя кнопка.
    "stage_scenes": "Нарезать сцены",
    "stage_scenes_hint": "Видео режутся на сцены PySceneDetect и ffmpeg (trim по кадрам), "
                         "один проход ffmpeg на видео. Каждый клип нормализуется здесь, один раз: fps, размер, звук.",
    "stage_scripts": "Сгенерировать funscript",
    "stage_scripts_hint": "Каждый клип отслеживается YOLO, для него пишется sidecar "
                          "`.funscript` — модель из настроек.",
    "stage_merge": "Склеить",
    "stage_merge_hint": "Отобранные клипы кодируются в один формат, склеиваются без "
                         "Отобранные клипы читаются на месте и склеиваются `-c copy`: без перекодирования и без копий — клипы уже нормализованы при резе — и пишется один склеенный funscript.",

    "label_source_videos": "Исходные видео",
    "label_scenes_out": "Папка сцен",
    "label_clips": "Папка клипов",
    "label_scripts": "Папка sidecar'ов",
    "label_result_dir": "Папка результата",
    "browse": "Обзор…",
    "open_folder": "Открыть",
    "start": "Запустить",
    "cancel": "Отмена",
    "running": "Идёт…",

    "min_waves": "Минимум волн (0 = без фильтра)",
    "max_waves": "Максимум волн (0 = без ограничения)",
    "sort_mode": "Порядок клипов",
    "result_name": "Имя результата",
    "pattern_clips": "Шаблон клипов",
    "sort_tick_rate": "По тикам в секунду (возрастает)",
    "sort_waves_asc": "По волнам, по возрастанию",
    "sort_waves_desc": "По волнам, по убыванию",
    "sort_keep": "Порядок имён",
    "sort_random": "Случайный порядок",

    # Вкладка настроек.
    "language": "Язык",
    "theme": "Цветовая схема",
    "theme_neon": "Neon",
    "theme_cartoons": "Cartoons",
    "theme_pink": "Pink",
    "jobs": "Процессы ffmpeg (стадия 1)",
    "threads": "Потоки torch (стадия 2)",
    "device": "Устройство для YOLO",
    "device_auto": "Авто (GPU, если есть)",
    "device_cpu": "CPU",
    "device_cuda": "CUDA",
    "model": "Модель YOLO",
    "model_default": "По умолчанию: {path}",
    "model_reset": "Вернуть модель по умолчанию",
    "model_bundled": "модель из сборки",
    "force": "Пересчитать sidecar'ы и переэнкодить сегменты",
    "no_check": "Пропустить проверки результата",
    "apply": "Применить",

    # Прогресс-бар: процент реальной работы, оценка, прошедшее время.
    "progress_idle": "Ожидание",
    "progress_units": "единиц",
    "unit_seconds": "с видео",
    "unit_frames": "кадров",
    "eta": "{pct}% · {done} / {total} · осталось {eta} · прошло {elapsed}",

    "console": "Консоль",
    "clear": "Очистить",

    # Одна строка стадии в консоли.
    "stage_start": "▶ {stage}: {source} → {out}",
    "stage_done": "✔ {stage}: готово за {elapsed} → {out}",
    "stage_failed": "✖ {stage}: {reason}",
    "stage_cancelled": "⛔ {stage}: остановлено пользователем",

    # Сообщения окна.
    "pick_source_first": "Сначала выберите папку исходных видео.",
    "no_videos": "В {dir} ({pattern}) видео нет.",
    "no_clips": "В {dir} ({pattern}) клипов нет.",
    "no_sidecars": "В {dir} sidecar'ов нет: сначала стадия 2.",
    "model_missing": "Модель {path} не найдена: выберите модель в настройках.",
    "locked_output": "{path} занят другим процессом (плеером): закройте его и повторите.",
    "one_stage": "Стадия уже запущена: дождитесь её окончания.",
    "pick_folder": "Выберите папку",
    "settings_save": "Сохранить",
    "settings_revert": "Сбросить",
    "settings_restart": "Перезапустить",
    "settings_saved": "Настройки сохранены.",
    "restart_needed": "Настройки сохранены: язык и схема применятся после перезапуска.",

    # Проверка обновлений.
    "check_updates": "Проверить обновления",
    "checking": "Проверяю…",
    "up_to_date": "Текущая версия {version} — последний релиз.",
    "new_version": "Доступен новый релиз {version} ({date}).",
    "download": "Скачать {file}",
    "downloading": "Скачиваю {file}…",
    "downloaded": "{file} сохранён в {dir}",
    "update_failed": "Проверка обновлений не удалась: {reason}",
    "no_release": "Репозиторий пока без релизов.",
    "updates_title": "Обновления",
    "close": "Закрыть",
    "cancel": "Отмена",
    "install_now": "Запустить установщик",
    "update_ready": "{file} скачан и проверен.",
    "sha_mismatch": "Скачанный файл не совпадает с опубликованным SHA-256.",
    "notes": "Заметки релиза",
}
