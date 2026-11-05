import os
import sys
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool, inspect, text
from alembic import context

# Agregar la raiz del proyecto al sys.path para importar app
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.config import settings
from app.core.database import Base
# Importar modelos para que Alembic los detecte
from app.modules.auth.models import Usuario, Clinica, Rol, Permiso, RolPermiso, TokenBlacklist, Auditoria, Plan, VersionPlan  # noqa: F401
from app.modules.appointments.models import Especialidad, Medico, MedicoEspecialidad, Cita, ServicioMedico, HorarioMedico, BloqueoAgenda  # noqa: F401
from app.modules.medical_records.models import Paciente, FichaClinica  # noqa: F401
from app.modules.medical_records.hce.models import HistoriaClinica, Consulta, Diagnostico  # noqa: F401
from app.modules.medical_records.clinical_documents.models import DocumentoClinico  # noqa: F401
from app.modules.medical_records.prescriptions.models import (  # noqa: F401
    Medicamento, Receta, RecetaDetalle, ConfiguracionRecetas,
    SecuenciaRecetas, RecetaIdempotencia, RecetaValidacionIntento,
)
from app.modules.payments.models import Pago, Comprobante  # noqa: F401
from app.modules.medical_records.tratamientos.models import (  # noqa: F401
    Tratamiento, TratamientoMedicamento, TratamientoDosis, TratamientoEvento,
)
from app.modules.medical_records.tratamientos.avisos_models import (  # noqa: F401
    TratamientoAviso, TratamientoDispositivo, TratamientoEntregaPush, TratamientoCursor,
)
from app.modules.backup.models import BackupConfig  # noqa: F401
from app.modules.tenants.models import (  # noqa: F401
    PlanVersion, TenantRequest, TenantRequestTrackingAudit, TenantSubscription, SubscriptionPayment, SubscriptionChange,
)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Establecer dinámicamente la URL de la base de datos desde settings
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Model metadata for autogenerate support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            # Do not rewrite shared revision 020. Refuse its historical name-based
            # backfill BEFORE it executes, even for direct `alembic upgrade head`.
            destination = context.get_revision_argument()
            if destination and inspect(connection).has_table('plan_versions'):
                from alembic.script import ScriptDirectory
                script = ScriptDirectory.from_config(config)
                targets = tuple(rev.revision for rev in script.get_revisions(destination))
                target_history = {rev.revision for rev in script.iterate_revisions(targets, 'base')}
                current = context.get_context().get_current_heads()
                applied = {rev.revision for rev in script.iterate_revisions(current, 'base')} if current else set()
                if ('cu34_consolidacion_020' in target_history and 'cu34_consolidacion_020' not in applied
                        and connection.scalar(text('SELECT count(*) FROM plan_versions'))):
                    raise RuntimeError('CU35: detener antes de 020 main; hay versiones legacy y su backfill por nombre no esta autorizado. Conciliar en copia con mapas explicitos.')
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
