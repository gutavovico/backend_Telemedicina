# `auth/_legacy/` — restos archivados

No es código de producción. Nada aquí se importa: `app/main.py` solo registra
`app.modules.auth.router`.

---

## `login/router.py`

Refactor abandonado de los endpoints de autenticación (CU01 / CU23). El código
vivo equivalente está en `app/modules/auth/router.py`.

### Por qué se archivó en vez de simplemente borrarse

El archivo es **inelegible para montarse tal cual**, pero documenta el diseño
que el proyecto perseguiría, así que conservarlo vale la pena:

1. **Importa módulos que ya no existen.** En las líneas 7 y 14 importa
   `app.modules.auth.login.schemas` y `app.modules.auth.login.service`. Esos
   fuentes fueron borrados; solo queda su bytecode en
   `_legacy/bytecode/app/modules/auth/login/`. Montar este router produciría
   `ModuleNotFoundError` de inmediato.

2. **Accede a una columna ausente en el ORM.** Las líneas 58, 101 y 117 leen y
   escriben `user.token_version`, pero `Usuario` en
   `app/modules/auth/models.py` **no declara esa columna**. Como el modelo
   SQLAlchemy no la mapea, `user.token_version` lanza `AttributeError` en
   tiempo de ejecución, no de compilación.

   Matiz: la columna **sí existe en la base de datos real** de Neon
   (`usuarios.token_version`, verificada por consulta). La divergencia está
   entre el modelo ORM y la BD, no en la BD.

### Lo que este archivo revela del diseño previsto

Es la única fuente del repo que documenta la intención de seguridad:

| Intención | Dónde | Estado |
|---|---|---|
| Claim `tenant_id` en el JWT | línea 62, 120 | **No implementado** en `auth/router.py` |
| Claim `token_version` para revocar sesiones | línea 58, 101 | **No implementado**; la columna existe en BD pero no en el ORM |
| Revocar refresh tokens revocados | línea 101-106 | **No implementado**; existe la tabla `token_blacklist` en BD |
| `/auth/me` devolviendo `tenant_id` | línea 144 | **No implementado**; el `/me` vivo no lo devuelve |

Los cuatro puntos son relevantes para CU23 (cierre de sesión) y para el
aislamiento por tenant que exigen CU10 y CU12. Si se retoma la revocación de
sesiones, la tabla `token_blacklist` y la columna `token_version` ya están
creadas y solo falta mapearlas en el modelo.
