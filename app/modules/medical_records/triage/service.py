import os
import json
from fastapi import UploadFile, HTTPException
from google import genai
from google.genai import types

from app.modules.medical_records.triage.schemas import TriageForm, TriageResponse
from app.modules.medical_records.triage.reglas_triaje import calcular_nivel_manchester, COLORES, DESCRIPCIONES, TIEMPOS_ATENCION

from dotenv import load_dotenv

def _get_gemini_client():
    load_dotenv() # Recargar .env en caso de que se haya modificado
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY no configurada")
    return genai.Client(api_key=api_key)

def build_gemini_prompt(form: TriageForm, nivel_reglas: int) -> str:
    return f"""Eres un asistente de triaje de un consultorio virtual. Solo atiendes consultas de salud; si preguntan otra cosa, indica que no puedes ayudar. No das diagnósticos definitivos: das posibles causas, justificas la prioridad y recomiendas atención médica. Responde en español y solo en JSON con el esquema indicado.
    
Paciente presenta:
- Motivo: {form.motivo}
- Intensidad de dolor: {form.intensidad_dolor}/10
- Tiempo de evolución: {form.tiempo_evolucion}
- Signos de alarma: {', '.join(form.signos_alarma) if form.signos_alarma else 'Ninguno'}
- Descripcin: {form.consulta_directa}

El sistema experto calculó un nivel base de {nivel_reglas}. 
REGLA CLAVE: Puedes SUBIR la urgencia (es decir, reducir el nivel a 1, 2 etc. si ves signos ocultos) pero NUNCA bajarlo (es decir, si el experto dijo 2, no puedes devolver 3).

Devuelve estrictamente un JSON con:
- nivel (int: 1-5, donde 1 es más grave)
- posibles_causas (list of strings: incluye una breve y clara explicación comprensible para un paciente sobre por qué sospechas esto. Ej: "Gastroenteritis: una posible infección estomacal")
- recomendaciones (list of strings: en lenguaje sencillo)
- motivo_clasificacion (string: explicación en lenguaje amigable y sin jerga médica de por qué asignaste ese nivel)
"""

async def analizar_triaje_ia(form: TriageForm, files: list[UploadFile] = None) -> TriageResponse:
    nivel_base = calcular_nivel_manchester(form.motivo, form.intensidad_dolor, form.tiempo_evolucion, form.signos_alarma)
    
    client = _get_gemini_client()
    
    contents = [build_gemini_prompt(form, nivel_base)]
    
    # Process files
    # Note: For production we would upload them via client.files.upload() or send base64 depending on API preference.
    # The new SDK `google-genai` can accept types.Part.from_bytes.
    if files:
        for file in files:
            file_bytes = await file.read()
            mime_type = file.content_type
            contents.append(
                types.Part.from_bytes(
                    data=file_bytes,
                    mime_type=mime_type,
                )
            )

    try:
        response = client.models.generate_content(
            model='gemini-3.8-flash',
            contents=contents,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
    except Exception as e_main:
        print(f"gemini-3.8-flash failed ({e_main}), falling back to gemini-1.5-flash...")
        try:
            response = client.models.generate_content(
                model='gemini-1.5-flash',
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                ),
            )
        except Exception as e_fallback:
            raise HTTPException(status_code=503, detail=f"Error en IA: {str(e_fallback)}")
        
    try:
        ia_data = json.loads(response.text)
        nivel_ia = int(ia_data.get("nivel", nivel_base))
        
        # Enforce Rule: never lower urgency
        # Urgency is higher when number is lower (1 > 2)
        nivel_final = min(nivel_ia, nivel_base) 
        
        return TriageResponse(
            nivel=nivel_final,
            color=COLORES.get(nivel_final, "Azul"),
            descripcion_nivel=DESCRIPCIONES.get(nivel_final, "No urgente"),
            tiempo_atencion_max_min=TIEMPOS_ATENCION.get(nivel_final, 240),
            posibles_causas=ia_data.get("posibles_causas", []),
            recomendaciones=ia_data.get("recomendaciones", []),
            motivo_clasificacion=ia_data.get("motivo_clasificacion", "Clasificado por sistema experto"),
        )
    except Exception as e:
        # Fallback to rules if JSON parsing fails
        return obtener_triaje_preliminar(form)

def obtener_triaje_preliminar(form: TriageForm) -> TriageResponse:
    nivel = calcular_nivel_manchester(form.motivo, form.intensidad_dolor, form.tiempo_evolucion, form.signos_alarma)
    return TriageResponse(
        nivel=nivel,
        color=COLORES.get(nivel, "Azul"),
        descripcion_nivel=DESCRIPCIONES.get(nivel, "No urgente"),
        tiempo_atencion_max_min=TIEMPOS_ATENCION.get(nivel, 240),
        posibles_causas=["Pendiente análisis detallado"],
        recomendaciones=["Complete el formulario y adjunte evidencias para un análisis con IA"],
        motivo_clasificacion="Evaluación preliminar por sistema experto",
    )
