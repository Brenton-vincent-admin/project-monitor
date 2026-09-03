import json
from pathlib import Path


DEFAULT_CONFIG = {
    "cooldown_hours": 5,
    "csv_path": "",
    "data_dir": "",
}


class ConfigManager:
    def __init__(self, config_path):
        self.path = Path(config_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.config = dict(DEFAULT_CONFIG)
        self._load()

    def _load(self):
        if self.path.exists():
            with open(self.path) as f:
                saved = json.load(f)
            self.config.update(saved)

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self.config, f, indent=2)

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self.save()

    @property
    def cooldown_hours(self):
        return self.config.get("cooldown_hours", 5)

    @property
    def cooldown_seconds(self):
        return self.cooldown_hours * 3600

    @property
    def csv_path(self):
        return self.config.get("csv_path", "")
