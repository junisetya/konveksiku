#!/usr/bin/env bash
# Compile-check + jalankan pemeriksaan cepat.
set -u
cd "$(dirname "$0")/.." || exit 2
python -c "import py_compile; py_compile.compile('app.py', doraise=True); py_compile.compile('tools/check.py', doraise=True); print('COMPILE_OK')" || exit 1
python tools/check.py || exit 1
if command -v node >/dev/null 2>&1; then
  node tools/check_js.js || exit 1
fi
