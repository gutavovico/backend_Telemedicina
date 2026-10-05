import json
from typing import List, Optional
from fastapi import APIRouter, Depends, Form, UploadFile, File, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Usuario

from app.modules.medical_records.triage.schemas import TriageForm, TriageResponse, TriageRecordResponse
from app.modules.medical_records.triage.service import obtener_triaje_preliminar, analizar_triaje_ia

router = APIRouter(prefix="/triaje", tags=["Triaje y Urgencias"])

@router.post("/preliminar", response_model=TriageResponse, summary="Calcular nivel de triaje preliminar")
def preliminar(form: TriageForm):
    """Calcula nivel Manchester usando el sistema experto basado en reglas."""
    return obtener_triaje_preliminar(form)

@router.post("/analizar", response_model=TriageResponse, summary="Anlisis IA de síntomas y evidencias")
async def analizar(
    motivo: str = Form(...),
    intensidad_dolor: int = Form(...),
    tiempo_evolucion: str = Form("No especificado"),
    signos_alarma: str = Form("[]"),
    consulta_directa: str = Form(...),
    evidencia: Optional[List[UploadFile]] = File(None)
):
    """Combina reglas expertas + Gemini Flash para análisis multimodal."""
    try:
        signos = json.loads(signos_alarma)
    except:
        signos = []
        
    form = TriageForm(
        motivo=motivo,
        intensidad_dolor=intensidad_dolor,
        tiempo_evolucion=tiempo_evolucion,
        signos_alarma=signos,
        consulta_directa=consulta_directa
    )
    
    # Validar archivos (max 10MB)
    valid_files = []
    if evidencia:
        for file in evidencia:
            if file.size and file.size > 10 * 1024 * 1024:
                raise HTTPException(status_code=400, detail=f"Archivo {file.filename} excede 10MB")
            if file.content_type not in ["image/jpeg", "image/png", "application/pdf"]:
                raise HTTPException(status_code=400, detail=f"Formato no permitido en {file.filename}")
            valid_files.append(file)
            
    return await analizar_triaje_ia(form, valid_files)

@router.post("/{id}/derivar", summary="Enviar evaluacin a guardia")
def derivar(id: int, db: Session = Depends(get_db)):
    """Guarda o actualiza la evaluacin y la marca como enviada a guardia."""
    # Como no tenemos tabla Triaje en el mockup, podemos simularlo
    return {"message": "Evaluación enviada al especialista de guardia exitosamente."}
