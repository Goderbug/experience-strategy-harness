import { mkdir, copyFile, readdir, readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

// A release tarball carries the Python runtime; it never depends on a sibling checkout.
const destination = new URL('./scripts/', import.meta.url);
await mkdir(destination, { recursive: true });
for (const name of ['runtime.py', 'harness.py']) {
  await copyFile(new URL(`../../scripts/${name}`, import.meta.url), new URL(name, destination));
}
for (const directory of ['references', 'templates']) {
  await mkdir(new URL(`./${directory}/`, import.meta.url), { recursive: true });
  for (const file of await readdir(new URL(`../../${directory}/`, import.meta.url))) {
    if (file.endsWith('.md')) await copyFile(new URL(`../../${directory}/${file}`, import.meta.url), new URL(`./${directory}/${file}`, import.meta.url));
  }
}
for (const file of ['SKILL.md', 'EXPERIENCE-HARNESS.md']) {
  const text = await readFile(new URL(`../../${file}`, import.meta.url), 'utf8');
  // In this smaller DSH package adapter docs live in the repository; the method
  // and state protocol themselves keep their original local paths.
  const portable = text.replaceAll('(adapters/codex/README.md)', '(https://github.com/Goderbug/experience-strategy-harness/tree/v0.2.0/adapters/codex)')
    .replaceAll('(adapters/deepseek/README.md)', '(README.md)');
  await writeFile(new URL(`./${file}`, import.meta.url), portable);
}
console.log(`Bundled runtime: ${fileURLToPath(destination)}`);
