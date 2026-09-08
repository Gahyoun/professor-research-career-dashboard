import { spawnSync } from 'node:child_process';
import { writeFileSync, readdirSync } from 'node:fs';

const compiled = spawnSync(process.execPath, ['node_modules/typescript/bin/tsc', '-p', 'tsconfig.tests.json'], { stdio: 'inherit' });
if (compiled.status !== 0) process.exit(compiled.status || 1);
writeFileSync('work/test-dist/package.json', '{"type":"commonjs"}\n');
const tested = spawnSync(process.execPath, ['--test', ...readdirSync('tests').filter(name => name.endsWith('.test.mjs')).map(name => `tests/${name}`)], { stdio: 'inherit' });
process.exit(tested.status ?? 1);
