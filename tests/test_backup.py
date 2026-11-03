"""Pruebas del dominio backup (cambio backup-copias-seguridad).

Solo cubren lógica sin BD ni pg_dump: schemas, nombres, URL libpq y
retención sobre un BACKUP_DIR temporal.
"""

import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.modules.backup import service
from app.modules.backup.schemas import BackupConfigUpdate


def test_config_update_valida():
    datos = BackupConfigUpdate(hora="02:00", dias_semana=["lun", "vie"],
                               activo=True, retencion_dias=7)
    assert datos.hora == "02:00"


def test_config_update_hora_invalida():
    with pytest.raises(ValueError):
        BackupConfigUpdate(hora="25:00", dias_semana=["lun"],
                           activo=True, retencion_dias=7)


def test_config_update_dias_vacios_e_invalidos():
    with pytest.raises(ValueError):
        BackupConfigUpdate(hora="02:00", dias_semana=[],
                           activo=True, retencion_dias=7)
    with pytest.raises(ValueError):
        BackupConfigUpdate(hora="02:00", dias_semana=["lunes"],
                           activo=True, retencion_dias=7)


def test_libpq_url_sin_driver():
    url = service._libpq_url()
    assert "+psycopg2" not in url
    assert url.startswith("postgresql://")


def test_leer_backup_invalido_y_traversal():
    with pytest.raises(HTTPException):
        service.leer_backup("otro.txt")
    with pytest.raises(HTTPException):
        service.leer_backup("../app/main.py")
    with pytest.raises(HTTPException):
        service.leer_backup("backup_20261008_020000.sql")  # no existe


def test_limpiar_antiguos_respeta_retencion(tmp_path, monkeypatch):
    monkeypatch.setattr(service.settings, "BACKUP_DIR", str(tmp_path))
    viejo = tmp_path / "backup_20200101_020000.sql"
    viejo.write_text("-- viejo")
    nuevo = tmp_path / "backup_20990101_020000.sql"
    nuevo.write_text("-- nuevo")
    import os, time
    os.utime(viejo, (time.time() - 30 * 86400, time.time() - 30 * 86400))
    eliminados = service.limpiar_antiguos(7)
    assert eliminados == 1
    assert not viejo.exists()
    assert nuevo.exists()


def test_listar_ordena_desc(tmp_path, monkeypatch):
    monkeypatch.setattr(service.settings, "BACKUP_DIR", str(tmp_path))
    for nombre in ("backup_20261001_020000.sql", "backup_20261008_020000.sql"):
        (tmp_path / nombre).write_text("-- x")
    archivos = service.listar_backups()
    assert [a.nombre for a in archivos] == [
        "backup_20261008_020000.sql", "backup_20261001_020000.sql"]
