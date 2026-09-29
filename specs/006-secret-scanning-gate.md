# Spec 006: Gate de Escaneo de Secretos

## 1. Problema

Una API key de Context7 (`ctx7sk-...`) fue commiteada en `opencode.json` en
línea de comando. La limpieza del historial se hizo manualmente (amend +
force-push + `git gc`). Ese incidente dio origen a dos carencias:

1. No existía ningún control automático que impida commitear un secreto.
2. Los hooks declarados en `opencode.json` bajo `hooks:` no son válidos en
   OpenCode `1.18.33`; `opencode debug config` los descarta silenciosamente.
   Además, hooks de herramientas no se ejecutan para comandos lanzados
   directamente en la terminal, que es el caso de uso real de un commit.

## 2. Objetivo

Escaneo determinista de secretos en cada commit, sin dependencia de LLM ni de
capas de herramientas, y con reglas propias del proyecto.

## 3. Alcance

**Incluido:** escaneo del working tree y del historial, hook de `pre-commit`,
reglas custom, allowlist acotada, documentación.

**Fuera de alcance (decisión explícita):** mover a variables de entorno las
credenciales de infraestructura ya presentes en `ansible-infra/`. Ese trabajo
no se pidió y queda como riesgo aceptado (ver §7). Tampoco se implementa la
capa de validadores LLM: se evaluó y se postergó por costo y latencia.

## 4. Componentes

| Archivo | Rol |
|---------|-----|
| `.gitleaks.toml` | Reglas + allowlist. Extiende el ruleset por defecto. |
| `.pre-commit-config.yaml` | Hook local que invoca gitleaks sobre el staging area. |
| `.gitignore` | Evita staging de secretos locales (`.env`, `*.pem`, `*.key`). |

### 4.1 Reglas custom

gitleaks **no trae ninguna regla para Context7**. Verificado empíricamente: el
ruleset por defecto responde `no leaks found` sobre un archivo que contiene una
key `ctx7sk-...` de formato válido. Sin la regla `anomalia-context7-api-key`,
este gate no habría atrapado el incidente que lo origina.

| Regla | Detecta |
|-------|---------|
| `anomalia-context7-api-key` | `ctx7sk-` seguido de 20+ caracteres |
| `anomalia-bearer-literal` | `Authorization: Bearer <20+ chars>` literal |

## 5. Decisiones de diseño

### 5.1 Hook local en lugar del oficial

En `v8.30.1` el hook upstream `gitleaks-system` se declara **sin**
`pass_filenames: false`. Consecuencia medida: `pre-commit` le pasa los nombres
de archivo como argumento posicional, gitleaks intenta `cd` hacia el archivo,
falla con `cannot change to '<archivo>'`, imprime `no leaks found` y **sale con
código 0**.

El gate resulting pasa todos los commits en verde sin escanear: peor que no
tener control, porque da confianza falsa. Por eso el hook se declara `repo:
local` con `pass_filenames: false` explícito. Si upstream lo corrige, se puede
migrar al repo oficial.

### 5.2 Versión pinneada

`.pre-commit-config.yaml` fija `rev: v8.30.1`. Nunca una versión flotante: un
`main` con reglas más estrictas rompería commits de forma inesperada.

`gitleaks-system` consume el binario del `PATH`, así que la versión del binario
debe coincidir con el `rev`. Se documenta el procedimiento de actualización en
`AGENTS.md`.

### 5.3 Allowlist por path

La allowlist se define por ruta, nunca por valor. Una allowlist por valor
permitiría que pasara cualquier otra credencial con el mismo string.

## 6. Validación

Verificado sobre el repo real (234 archivos versionados, 7 commits):

| Prueba | Resultado |
|--------|-----------|
| `gitleaks git .` sobre historial completo | 0 leaks |
| `pre-commit run --all-files` | limpio |
| Fixture `ctx7sk-` + `Bearer` en staging | **bloqueado**, 2 findings |
| Fixture con clave privada RSA | **bloqueado**, `private-key` |
| Commit con secretos (post-limpieza) | no creado |

Se usó un test de cordura con fixtures **no detectables** (`ghp_` de caracteres
repetidos, `EXAMPLEKEY` de AWS) que gitleaks no marca por diseño — checksum
inválido y allowlist explícita. Un `0 findings` sobre esos fixtures no hubiera
probado nada; se reemplazaron por fixtures de alta entropía reales.

## 7. Riesgos aceptados

- **Passwords de baja entropía fuera de cobertura.** gitleaks detecta alta
  entropía y proveedores conocidos. `anomal_password`, `admin_password` y
  `change-me-secret` en `ansible-infra/` no se marcan. RIESGO ACEPTADO: no se
  agreed agregar reglas que marquen esos paths, porque producirían una
  allowlist permanente sin resolver el problema de fondo. La mitigación real es
  externalizarlos a variables de entorno o Ansible Vault, fuera de alcance.
- **Bypass local.** `--no-verify` desactiva el hook. En un equipo, cualquiera
  con acceso al repo puede saltearlo. Mitigación futura: stage de CI con el
  mismo escaneo. Aceptado para un repo de un solo desarrollador.
- **Clave no rotada.** La key de Context7 fue limpiada del historial pero
  nunca rotada. Sigue siendo válida. Rotarla es responsabilidad del usuario.

## 8. Procedimiento ante un hallazgo legítimo

```bash
SKIP=gitleaks git commit
```

Preferir siempre corregir el código. `--no-verify` desactiva todos los hooks y
debe reservarse para emergencias.
