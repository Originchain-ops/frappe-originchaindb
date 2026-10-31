"""Create headless Bench directory/config scaffolding for disposable CI only."""

import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
for folder in ["sites/assets", "logs", "config"]:
    (root / folder).mkdir(parents=True, exist_ok=True)
(root / "sites/apps.txt").write_text("frappe\nerpnext\n")
(root / "sites/assets/assets.json").write_text("{}")
(root / "sites/assets/assets-rtl.json").write_text("{}")
(root / "sites/common_site_config.json").write_text(
    json.dumps(
        {
            "redis_cache": "redis://127.0.0.1:6379/0",
            "redis_queue": "redis://127.0.0.1:6379/1",
            "redis_socketio": "redis://127.0.0.1:6379/2",
            "developer_mode": 1,
            "server_script_enabled": 1,
            "socketio_port": 9000,
        }
    )
)
(root / "connection.json").write_text(
    json.dumps(
        {
            "db_type": "postgres",
            "db_backend": "originchaindb",
            "originchaindb_experimental": True,
            "originchaindb_reference_postgres": True,
            "db_sslmode": "disable",
            "db_host": "127.0.0.1",
            "db_port": 5432,
            "db_name": "oc_reference",
            "db_user": "probe",
            "db_password": "reference-only",
            "db_schema": "public",
            "developer_mode": 1,
            "allow_tests": True,
        }
    )
)
