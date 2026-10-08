# Spec 013 — Topología Flexible e Idempotencia (Inventario = Única Fuente)

**Estado:** Vigente
**Ámbito:** Ansible (`ansible-infra/`), propagación de playbooks al worker backend
**Invariancia:** TODO desarrollo de infraestructura debe cumplir este documento.

---

## 1. Motivación

La instalación de Anomalia debe decidirse libremente desde el **inventario**, nunca
asumida por el código. Quien instala coloca las IPs que desee en cada grupo; un mismo
**host puede pertenecer a cualquier combinación de grupos**. Una instalación local
(todas las IPs → `localhost`) es un caso particular válido, **no** el diseño objetivo.

Historias que este documento resuelve:

- Distribuir VictoriaMetrics (storage / insert / select) en hosts distintos.
- Repartir vlogs / traces / pyroscope / vmagent / vmauth / alertmanager / vmalert en
  los nodos que se quiera, repitiendo hostnames entre grupos libremente.
- `destroy-infra.yml` debe dejar la máquina **exactamente** como estaba, incluidas las
  unidades **derivadas** `anomalia-vmalert-*.service` (por-tenant).
- El worker del backend (Flutter/web) debe poder aprovisionar vmalert por-tenant vía
  los playbooks raíz, en el mismo formato y con las mismas garantías que el deploy.

---

## 2. Principios Invariantes

### 2.1 El inventario es la única fuente de topología
- Los grupos son: `all_nodes`, `vlogs_storage_nodes`, `vlogs_insert_nodes`,
  `vlogs_select_nodes`, `vm_storage_nodes`, `vm_insert_nodes`, `vm_select_nodes`,
  `vt_storage_nodes`, `vt_insert_nodes`, `vt_select_nodes`, `pyroscope_nodes`,
  `vmauth_nodes`, `vmagent_nodes`, `alertmanager_nodes`, `vmalert_nodes`,
  `backend_nodes`, `parses_nodes`.
- Nadie asume "todo en un monólito" ni "todos los nodos en todos los grupos".
- Un host puede repetirse en cualquier combinación de grupos (un solo host local es un
  caso particular).

### 2.2 Cada unidad systemd se despliega solo en los hosts de su grupo
- **Por unidad, no "por role en bloque":** en `victorialogs`/`victoriametrics`/
  `victoriatraces` cada task (storage dir + unit storage/insert/select) va condicionada
  a su grupo (`inventory_hostname in groups.get('<grupo>', [])`). Un host puede tener
  solo `vlinsert` sin `vlstorage`, etc.
- Roles de componente único (pyroscope, vmauth, vmagent, alertmanager, vmalert) se
  ejecutan en `deploy-infra.yml` solo con `when: inventory_hostname in groups.get('<grupo>', [])`.
- `backend` → `backend_nodes`; `parses` → `parses_nodes` (ya existente).

### 2.3 Referencias cruzadas entre componentes
- Siempre vía `hostvars[groups['X'][0]]`, prefiriendo la **IP de servicio**
  (`*_ip`) con `fallback a ansible_host` y luego a `127.0.0.1`, y **tolerando grupos
  vacíos u omitidos** con `groups.get('X', [])` (+ rama de fallback cuando es legítimo).
- En templates, si el grupo puede faltar: dividir el acceso en `{% set %}` con rama
  condicional, o `| first | default('')` / `groups.get('X', [])`, nunca `groups['X']`
  a secas.

### 2.4 Idempotencia estricta
- Toda task debe repetirse sin efectos colaterales (no duplicación de units, reglas,
  filas, redes). Los `ON CONFLICT`/`state=present` y la convergencia por `find` son la
  norma.

### 2.5 Destroy completo
- `destroy-infra.yml` retira **todo** lo que `deploy` crea, incluidas las units
  **derivadas por-tenant** `anomalia-vmalert-*.service` descubiertas por `find`
  (nunca hardcodear slugs ni hostnames).
- **Unidades ausentes = OK, no error:** los loops que detienen servicios systemd
  usan `register` + `failed_when` que tolera los mensajes
  `could not find the requested service` / `does not exist` (mismo idiom que
  `roles/vmalert`), en vez de `ignore_errors`. Justificación: la unit single
  `anomalia-vmalert.service` no existe en modo por-tenant (`vmalert_per_tenant=true`,
  spec 011 §4.1/§4.8) y, con topología flexible, cada host solo tiene "sus" units.
  Un error real de systemd (permisos, daemon roto) **sí** falla la task y queda
  visible.
- Se conservan solo las imágenes base compartidas (`postgres`, `ollama`) y
  `/opt/anomalia/certs`.

---

## 3. Propagación de Playbooks (fuente de verdad)

- **Autoritativos:** los playbooks raíz de `ansible-infra/`
  (`deploy-infra.yml`, `destroy-infra.yml`, `install-binaries.yml`, `sync-*.yml`).
- El role `backend` los copia en deploy-time a `/opt/anomalia/backend/playbooks` y el
  `COPY . .` del Dockerfile los hornea en `/app/playbooks` de la imagen. El worker
  ejecuta **esa copia raíz**, nunca un duplicado local.
- `roles/backend/src/` es **legado muerto**: nada lo referencia y **no se mantiene**
  (no sincronizar fixes allí; editar las plays raíz).

---

## 4. Worker del Backend (aprovisionamiento programático)

- Mecanismo: `ansible-playbook -i <ip>,` (host único, grupos vacíos) sobre
  `/app/playbooks/install-binaries.yml`, con extra-vars `servicio=vmalert`,
  `gestionar_servicios=true`, `vmalert_instances` (spec 011 / spec 012).
- Por ello los guards toleran el caso ad-hoc: donde un play exige pertenecer a un
  grupo, se admite también `groups.get('all', []) | length == 1` (inventario de un
  solo host del worker, sin grupos definidos).

---

## 5. Lista de Verificación (aplicar en todo cambio)

- [ ] Todo groupo accedido con `groups.get('X', [])` (o rama condicional), nunca
      `groups['X']` directo.
- [ ] Cada unit/artifact condicionado a su grupo (no a "all nodes").
- [ ] Cross-refs con `*_ip | default(ansible_host) | default('127.0.0.1')`.
- [ ] Guard ad-hoc del worker donde haga falta (`grupos.get('all', []) | length == 1`).
- [ ] `destroy` retira unidades derivadas por-tenant vía `find` (expandir cuando se
      agreguen nuevas unidades derivadas) y tolera unidades ausentes con
      `failed_when` por substring (`could not find…`/`does not exist`), no con
      `ignore_errors` (§2.5).
- [ ] Idempotencia verificada; `--check` razonable por escenario (all-in-one, multi
      grupos, destroy con units presentes).
- [ ] Sync: editar plays/roles raíz, NO `roles/backend/src/`.