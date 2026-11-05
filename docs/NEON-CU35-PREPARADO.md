# Preparación de Neon CU35 — decisión del 2026-11-05

El responsable autoriza ADOPTAR como ancla el día UTC de fecha_inicio de las dos
suscripciones existentes, condicionado a que fecha_fin sea el aniversario exacto
del mes siguiente, ajustado al último día del mes corto. No es evidencia recuperada
del ancla histórica ni una regla para inferir anclas de otras suscripciones.

La lectura con transaction_read_only=on confirma:

| Contrato | Inicio UTC | Cierre UTC | Importe pagado | Ancla adoptada |
|---|---|---|---|---|
| Versión 1 | 2026-11-05T05:29:41.470415Z | 2026-12-05T05:29:41.470415Z | 125.00 BOB | 5 |
| Versión 2 | 2026-11-05T05:48:08.774346Z | 2026-12-05T05:48:08.774346Z | 250.00 BOB | 5 |

Ambas relaciones de aniversario cumplen. Ambas referencias legacy son NULL;
se conservan las versiones canónicas 1/2, fechas, estados, importes e historial.
No se necesitan mapas de versiones para este estado. billing_anchor_map se
preparó con ambas claves reales y valor 5, solo en el archivo PRIVADO:
C:/Users/hp/Desktop/si2G3-5/.local-cu35-config/billing-anchor-map.json.
La evidencia/decisión está en billing-anchor-decision.json de esa misma carpeta.
No se incluyen esos archivos, configuraciones ni credenciales en el commit.

## Esquema realmente comprobado

En PostgreSQL 17 aislado se compararon Plan, VersionPlan, TenantSubscription,
SubscriptionPayment y SubscriptionChange contra la cadena real hasta
cu35_cu18_convergencia_023: todas las tablas/columnas, tipos, nulabilidad, PK,
FK (incluido RESTRICT al catálogo), restricciones únicas/CHECK e índices por
columnas, unicidad y presencia del predicado parcial. No se exige duplicar índices
equivalentes solo porque una revisión compartida use un nombre distinto.

Índices: búsqueda por entidad/versión en contratos y pagos, por suscripción y
sesión Stripe en pagos; entidad y clave idempotente, pago único y una solicitud
pendiente por suscripción en subscription_changes. El predicado cubre
WAITING_PAYMENT, SCHEDULED y WAITING_RENEWAL. Las pruebas de concurrencia validan
su efecto real. CU35 añade ancla, purpose/source_row_version/application_status/
application_reason/period_start/period_end y la tabla de solicitudes con todos
sus campos y relaciones. Los snapshots CU34 siguen protegidos contra edición.

Las dependencias clínicas/auth/auditoría existen y sus columnas usadas están
disponibles. Hay diferencias PREEXISTENTES de main fuera de estas cinco tablas:
usuarios carece de FKs declaradas en ORM hacia rol/clínica y telefono tiene
VARCHAR(20) frente a VARCHAR(30); medicos.id_clinica usa NO ACTION frente a
RESTRICT; fechas de auditoria/clinicas son WITHOUT TIME ZONE frente al ORM WITH
TIME ZONE, y descripcion de auditoria es TEXT. Algunos índices de PK declarados
en ORM son redundantes y no están creados como índices secundarios. No se
reestructuran esas tablas ni se afirma igualdad global de ORM/base. No se
identificó un fallo funcional CU35 por esas diferencias: están cubiertos actor,
aislamiento, auditoría y cierre en las regresiones. Revisión global queda al equipo.

Resultado final: 77 pruebas PostgreSQL aprobadas en la selección CU34/CU35,
incluidas diez CU35. También se comparó en solo lectura el esquema origen de
Neon contra la plantilla local en merge_cu18_asistencia_022: no faltan columnas,
FK ni índices de planes, versiones_plan, tenant_subscriptions y
subscription_payments. No se encontraron defectos de esquema propios de CU35.

## Copia Neon y comandos exactos

No hay credencial de gestión Neon ni conexión a una copia identificada disponible.
La conexión actual sigue en merge_cu18_asistencia_022; NO se migró. El acceso de
lectura no acredita permisos ni identidad de una copia apta para escribir.

En Neon Console, crear una copia desde el estado actual de la rama origen
br-rough-dew-ayxu0j2y del proyecto super-credit-95303158. Confirmar en el panel
que es una copia aislada, registrar su branch ID y guardar su conexión como
DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD en el archivo privado neon-copia.env
de .local-cu35-config, fuera de Git. No sustituir el .env actualizado del worktree.
Si la copia contiene más suscripciones, detenerse y ampliar la decisión/mapa.

Desde PowerShell, carpeta C:/Users/hp/Desktop/si2G3-5/.worktrees/cu35-backend-review:

```powershell
$cu35Python='C:/Users/hp/Desktop/si2G3-5/Telemmedicina-SDD/backend_Telemedicina/.venv-cu34/Scripts/python.exe'
$env:CU35_COPY_ENV_FILE='C:/Users/hp/Desktop/si2G3-5/.local-cu35-config/neon-copia.env'
$env:CU35_ANCHOR_MAP_FILE='C:/Users/hp/Desktop/si2G3-5/.local-cu35-config/billing-anchor-map.json'
$env:CU35_COPY_BRANCH_ID=Read-Host 'Branch ID de la copia aislada confirmada en Neon Console'
@'
from pathlib import Path
from argparse import Namespace
from calendar import monthrange
from datetime import timezone
import os, json
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import dotenv_values

root=Path.cwd()
v=dotenv_values(os.environ['CU35_COPY_ENV_FILE'],interpolate=False)
branch=os.environ['CU35_COPY_BRANCH_ID']
assert branch and branch!='br-rough-dew-ayxu0j2y', 'STOP: no usar la rama compartida'
assert (v.get('DB_HOST') or '').endswith('.neon.tech'), 'STOP: host no Neon'
anchors=json.loads(Path(os.environ['CU35_ANCHOR_MAP_FILE']).read_text(encoding='utf-8-sig'))
assert isinstance(anchors,dict) and anchors and all(type(x) is int and 1<=x<=31 for x in anchors.values())
def read():
    return psycopg2.connect(host=v['DB_HOST'],port=int(v.get('DB_PORT') or 5432),
        dbname=v['DB_NAME'],user=v['DB_USER'],password=v['DB_PASSWORD'],sslmode='require',
        options='-c default_transaction_read_only=on',connect_timeout=10)
tables={'tenant_subscriptions':'id_suscripcion',
        'subscription_payments':'id_pago_suscripcion','versiones_plan':'id'}
def snapshot(c):
    with c.cursor(cursor_factory=RealDictCursor) as q:
        result={}
        for table,pk in tables.items():
            q.execute('SELECT * FROM '+table+' ORDER BY '+pk)
            result[table]=[dict(row) for row in q.fetchall()]
        return result
with read() as c:
    with c.cursor() as q:
        q.execute('SHOW transaction_read_only'); assert q.fetchone()[0]=='on'
        q.execute("SELECT current_setting('neon.project_id',true),current_setting('neon.branch_id',true)")
        assert q.fetchone()==('super-credit-95303158',branch), 'STOP: identidad no coincide'
        q.execute('SELECT version_num FROM public.alembic_version')
        assert q.fetchall()==[('merge_cu18_asistencia_022',)], 'STOP: revisar revision base'
    before=snapshot(c)
    assert set(anchors)=={s['id_suscripcion'] for s in before['tenant_subscriptions']}, 'STOP: mapa incompleto'
    for s in before['tenant_subscriptions']:
        start=s['fecha_inicio'].astimezone(timezone.utc);end=s['fecha_fin'].astimezone(timezone.utc)
        year=start.year+(start.month==12);month=start.month%12+1
        assert end==start.replace(year=year,month=month,day=min(start.day,monthrange(year,month)[1]))
        assert anchors[s['id_suscripcion']]==start.day and s['ciclo']=='MONTHLY'
        assert s['id_plan_version'] is None and s['id_version_plan'] is not None
    assert all(p['id_plan_version'] is None and p['id_version_plan'] is not None
               for p in before['subscription_payments']), 'STOP: referencia legacy requiere conciliacion'
    c.rollback()

# Solo este proceso usa la conexion de COPIA. No modifica .env ni la terminal.
for key in ('DB_HOST','DB_PORT','DB_NAME','DB_USER','DB_PASSWORD'):
    os.environ[key]=str(v.get(key) or ('5432' if key=='DB_PORT' else ''))
os.environ.update(DB_SSLMODE='require',SUBSCRIPTION_CYCLE_WORKER_ENABLED='false')
from alembic.config import Config
from alembic import command
cfg=Config(str(root/'alembic.ini'))
cfg.set_main_option('script_location',str(root/'alembic'))
cfg.cmd_opts=Namespace(x=['billing_anchor_map='+json.dumps(anchors)])
command.upgrade(cfg,'head')
with read() as c:
    with c.cursor() as q:
        q.execute('SELECT version_num FROM public.alembic_version')
        assert q.fetchall()==[('cu35_cu18_convergencia_023',)]
    after=snapshot(c)
    for table,rows in before.items():
        assert len(rows)==len(after[table]), 'REVISAR: cambio en numero de filas'
        for old,new in zip(rows,after[table]):
            assert {key:new[key] for key in old}==old, 'REVISAR: cambio en historial/condiciones'
    c.rollback()
print('Copia migrada: revision final e historial previo conservados. Worker apagado.')
'@ | & $cu35Python -
```

El código valida identidad/revisión antes de escribir y rechaza la rama compartida
conocida. Aun así, confirmar la etiqueta de copia en el panel es un paso obligatorio;
un branch ID distinto por sí solo no demuestra que sea de prueba. Si falla una
validación posterior al upgrade, detener el despliegue y revisar la copia: no
ejecutar stamp/downgrade ni asumir rollback de una migración ya confirmada.
La prueba real en copia Neon y Stripe sandbox siguen pendientes; no se certifica
compatibilidad productiva ni se activa el worker con estas instrucciones.
