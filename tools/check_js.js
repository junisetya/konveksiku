// Cek syntax JavaScript yang tertanam di app.py.
// Jalankan: node tools/check_js.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
// UI dipisah ke rofi_ui.py sejak v2; app.py hanya mengimpornya.
const source = fs.readFileSync(path.join(root, 'rofi_ui.py'), 'utf8');

const marker = 'HTML = r"""';
const start = source.indexOf(marker);
if (start === -1) {
  console.error('Tidak menemukan blok HTML di app.py');
  process.exit(2);
}
const bodyStart = source.indexOf('<script>', start);
const bodyEnd = source.indexOf('</script>', bodyStart);
if (bodyStart === -1 || bodyEnd === -1) {
  console.error('Tidak menemukan blok <script>');
  process.exit(2);
}
const js = source.slice(bodyStart + '<script>'.length, bodyEnd);

try {
  new vm.Script(js, { filename: 'app-embedded.js' });
  console.log('JS SYNTAX OK (' + js.split('\n').length + ' baris)');
} catch (e) {
  console.error('JS SYNTAX ERROR: ' + e.message);
  const m = /app-embedded\.js:(\d+)/.exec(e.stack || '');
  if (m) {
    const line = Number(m[1]);
    const lines = js.split('\n');
    for (let i = Math.max(0, line - 4); i < Math.min(lines.length, line + 3); i++) {
      console.error((i + 1) + ': ' + lines[i]);
    }
  }
  process.exit(1);
}
