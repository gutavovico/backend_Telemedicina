from typing import List

TIEMPOS_ATENCION = {
    1: 0,
    2: 10,
    3: 30,
    4: 120,
    5: 240
}

COLORES = {
    1: "Rojo",
    2: "Naranja",
    3: "Amarillo",
    4: "Verde",
    5: "Azul"
}

DESCRIPCIONES = {
    1: "Inmediato - Riesgo vital",
    2: "Muy urgente - Riesgo vital potencial",
    3: "Urgente - Necesita atención rápida",
    4: "Normal - Urgencia menor",
    5: "No urgente - Puede posponerse"
}

def calcular_nivel_manchester(motivo: str, dolor: int, tiempo: str, signos: List[str]) -> int:
    # Reglas bsicas inspiradas en Manchester
    if any(s in signos for s in ["dificultad para respirar", "sangrado profuso", "prdida de fuerza o parlisis repentina"]):
        return 1
    if "confusin/desorientacin" in signos or dolor >= 9:
        return 2
    if "fiebre >39C resistente a antitrmicos" in signos or dolor >= 7:
        return 3
    if dolor >= 4 or tiempo in ["<2 horas", "hoy/pocas horas"]:
        return 4
    return 5
