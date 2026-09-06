# Re-exports for backward compatibility
from app.modules.medical_records.patient_profile.service import (
    get_patient_by_id,
    get_patient_by_ci,
    get_patient_by_user_id,
    list_patients,
    create_patient,
    update_patient,
    patch_patient_profile,
    soft_delete_patient,
)
