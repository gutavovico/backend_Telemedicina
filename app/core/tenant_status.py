"""Normalización de estados de tenant (CU30/CU32).

El contrato de CU30 usa ACTIVE | SUSPENDED | INACTIVE, mientras que los datos
legacy de `clinicas` usan ACTIVO | SUSPENDIDO | INACTIVO. Ambos deben leerse de
forma equivalente hasta completar la migración, sin que un tenant aprobado por
CU30 quede inaccesible o no pueda solicitar la baja.
"""
from typing import Tuple

CANONICAL_ACTIVE = "ACTIVE"
CANONICAL_SUSPENDED = "SUSPENDED"
CANONICAL_INACTIVE = "INACTIVE"

CANONICAL_STATES = (CANONICAL_ACTIVE, CANONICAL_SUSPENDED, CANONICAL_INACTIVE)

LEGACY_BY_CANONICAL = {
    CANONICAL_ACTIVE: "ACTIVO",
    CANONICAL_SUSPENDED: "SUSPENDIDO",
    CANONICAL_INACTIVE: "INACTIVO",
}

_CANONICAL_BY_LEGACY = {legacy: canonical for canonical, legacy in LEGACY_BY_CANONICAL.items()}


def canonical_tenant_status(value) -> str:
    """Devuelve ACTIVE/SUSPENDED/INACTIVE para cualquier variante almacenada."""
    if value is None:
        return ""
    normalized = str(value).strip().upper()
    if normalized in CANONICAL_STATES:
        return normalized
    return _CANONICAL_BY_LEGACY.get(normalized, normalized)


def tenant_status_variants(value) -> Tuple[str, ...]:
    """Variantes aceptadas por la BD para un estado canónico o legacy."""
    canonical = canonical_tenant_status(value)
    legacy = LEGACY_BY_CANONICAL.get(canonical)
    variants = {canonical}
    if legacy:
        variants.add(legacy)
    if value:
        variants.add(str(value).strip().upper())
    return tuple(sorted(v for v in variants if v))
