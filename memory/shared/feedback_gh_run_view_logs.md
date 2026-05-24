---
name: gh run view — usar --log-failed, no --log + grep
description: Para inspeccionar fallos de workflow GitHub Actions, --log-failed extrae solo el job/step que falló sin envoltura. Es más limpio que --log + grep manual.
type: feedback
originSessionId: b652f8dc-bb46-471e-8028-6a28a0140fea
---
Cuando un workflow de GitHub Actions falla y se necesita inspeccionar el error, usar:

```bash
gh run view <databaseId> --log-failed --repo <owner>/<repo>
```

en lugar de:

```bash
gh run view <databaseId> --log | grep <pattern>
```

**Why:** `--log-failed` filtra automáticamente solo los logs del job/step que falló. Es el equivalente a "show me the failure" sin tener que sortear logs de checkout, setup, etc. El log completo con `--log` es ruidoso (setup, env, group sections, secrets masking, etc.) y obliga a grep manual con regex frágil.

**Cómo aplicar:**
- Para fallos puntuales: `gh run view <id> --log-failed --repo <repo>`. Output limpio del step que reventó.
- Si solo se conoce el "run #N" de la UI de GitHub: ese número NO sirve directamente. Hay que obtener el `databaseId` (entero de 11 dígitos) con:
  ```bash
  gh run list --workflow="<name>" --limit 10 --json databaseId,number,conclusion --jq '.[] | "run #\(.number) (id=\(.databaseId)) [\(.conclusion)]"'
  ```
- Para el run más reciente fallado en un branch:
  ```bash
  gh run list --workflow="<name>" --branch=main --status=failure --limit 1 --json databaseId --jq '.[0].databaseId'
  ```

**Anotado tras sesión S60** cuando Jero corrigió mi patrón `gh run view <id> --log | grep "Changed resources"`.
