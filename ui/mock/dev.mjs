// `npm run dev:mock`: the mock backend and the Vite dev server together, pointed at each other.
// Extra arguments go to Vite (e.g. `npm run dev:mock -- --port 5199`).
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const port = process.env.MOCK_PORT ?? '8765'
const here = fileURLToPath(new URL('.', import.meta.url))

const mock = spawn(process.execPath, [`${here}server.mjs`], { stdio: 'inherit', env: { ...process.env, MOCK_PORT: port } })
const vite = spawn(`${here}../node_modules/.bin/vite`, process.argv.slice(2), {
  stdio: 'inherit',
  env: { ...process.env, VITE_API_URL: `http://localhost:${port}` },
})

const stop = () => {
  mock.kill()
  vite.kill()
}
for (const sig of ['SIGINT', 'SIGTERM']) process.on(sig, stop)
mock.on('exit', stop)
vite.on('exit', (code) => {
  mock.kill()
  process.exit(code ?? 0)
})
