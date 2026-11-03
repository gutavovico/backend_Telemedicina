"""Trabajador CU17: python -m scripts.run_cu17_notificaciones [--once|--interval 60]."""
import argparse
import logging
import time

from app.core.database import SessionLocal
from app.modules.medical_records.tratamientos.avisos import ejecutar_ciclo


logger = logging.getLogger("cu17.worker")


def run_once() -> bool:
    db = SessionLocal()
    try:
        result = ejecutar_ciclo(db)
        db.commit()
        logger.info("Ciclo CU17 completado: avisos=%s, entregas=%s, ocupado=%s",
                    result["avisos"], result["entregas"], result["ocupado"])
        if result["clinicas_sin_sistema"]:
            logger.error("CU17: configurar usuario SISTEMA para clínicas %s",
                         result["clinicas_sin_sistema"])
            return False
        return True
    except Exception:
        db.rollback()
        # No registrar excepciones del proveedor: podrían contener tokens.
        logger.error("El ciclo CU17 falló; se reintentará en el siguiente ciclo")
        return False
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generar y despachar recordatorios CU17")
    parser.add_argument("--once", action="store_true", help="Ejecutar un único ciclo")
    parser.add_argument("--interval", type=int, default=60, help="Segundos entre ciclos (mínimo 10)")
    args = parser.parse_args()
    if args.interval < 10:
        parser.error("--interval debe ser al menos 10 segundos")
    logging.basicConfig(level=logging.INFO)
    if args.once:
        return 0 if run_once() else 1
    while True:
        run_once()
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
