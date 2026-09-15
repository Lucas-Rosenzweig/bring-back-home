import { spawnSync } from 'node:child_process';
import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const args = process.argv.slice(2);
function run(command, arguments_) {
  const result = spawnSync(command, arguments_, { cwd: root, stdio: 'inherit' });
  if (result.error) {
    console.error(`Impossible de lancer ${command}: ${result.error.message}`);
    process.exit(1);
  }
  if (result.status !== 0) process.exit(result.status ?? 1);
}
if (['enable', 'disable', 'status'].includes(args[0])) {
  run('python3', ['scripts/fixtures.py', ...args]);
} else if (args.length) {
  console.error('Usage : npm test [enable|disable|status] [-- --db /chemin/base.db]');
  process.exit(1);
} else {
  const files = readdirSync(new URL('../tests/', import.meta.url))
    .filter(name => /\.test\.tsx?$/.test(name)).sort().map(name => `tests/${name}`);
  run(process.execPath, ['--import', 'tsx', '--test', ...files]);
  run('python3', ['-m', 'unittest', 'discover', '-s', 'tests', '-p', '*_test.py']);
}
