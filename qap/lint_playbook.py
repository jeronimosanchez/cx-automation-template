#!/usr/bin/env python3
"""
lint_playbook.py — Linter minimo para prompts de Playbooks Petal (v1.1).

Reglas:
  R1 — Sin acentos diacriticos
  R2 — Referencias a Playbooks deben usar ${PLAYBOOK:Name}, no backticks
  R3 — No usar $session_id como parametro

Uso:
  python lint_playbook.py <archivo.txt>
"""

import re
import sys
from pathlib import Path

ACENTOS_PATTERN = re.compile(r'[áéíóúñÁÉÍÓÚÑ]')
PLAYBOOK_BACKTICK_PATTERN = re.compile(r'`([A-Z][A-Za-z_]+)`')
SESSION_ID_PATTERN = re.compile(r'\$session_id')


def lint_file(path):
    issues = []
    with open(path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, start=1):
            # R1 - acentos: extrae palabra completa con acento
            seen_words = set()
            for match in ACENTOS_PATTERN.finditer(line):
                start = match.start()
                word_start = start
                while word_start > 0 and line[word_start - 1].isalpha():
                    word_start -= 1
                word_end = start + 1
                while word_end < len(line) and line[word_end].isalpha():
                    word_end += 1
                word = line[word_start:word_end]
                if word in seen_words:
                    continue
                seen_words.add(word)
                issues.append({
                    'line': line_num,
                    'severity': 'ERROR',
                    'rule': 'R1',
                    'message': f'acento detectado en "{word}"'
                })

            # R2 - playbook con backticks
            for match in PLAYBOOK_BACKTICK_PATTERN.finditer(line):
                name = match.group(1)
                issues.append({
                    'line': line_num,
                    'severity': 'ERROR',
                    'rule': 'R2',
                    'message': f'referencia a Playbook con backticks (`{name}`) -> debe ser ${{PLAYBOOK:{name}}}'
                })

            # R3 - $session_id
            if SESSION_ID_PATTERN.search(line):
                issues.append({
                    'line': line_num,
                    'severity': 'WARN',
                    'rule': 'R3',
                    'message': '$session_id usado como parametro'
                })
    return issues


def main():
    if len(sys.argv) < 2:
        print("Uso: python lint_playbook.py <archivo.txt>", file=sys.stderr)
        sys.exit(2)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Archivo no encontrado: {path}", file=sys.stderr)
        sys.exit(2)

    issues = lint_file(path)
    issues.sort(key=lambda x: (x['line'], x['rule']))

    for issue in issues:
        print(f"{issue['severity']:6} linea {issue['line']:3}: {issue['message']}")

    errors = sum(1 for i in issues if i['severity'] == 'ERROR')
    warnings = sum(1 for i in issues if i['severity'] == 'WARN')
    total = len(issues)

    print()
    if total == 0:
        print("No issues found.")
    else:
        print(f"{total} issues found ({errors} errors, {warnings} warnings)")

    sys.exit(1 if errors > 0 else 0)


if __name__ == '__main__':
    main()
