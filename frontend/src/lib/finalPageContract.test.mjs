import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const app = await readFile(new URL('../App.jsx', import.meta.url), 'utf8')
const finalPage = await readFile(new URL('../pages/FinalGamePage.jsx', import.meta.url), 'utf8')
const livePage = await readFile(new URL('../pages/LiveScoreboardPage.jsx', import.meta.url), 'utf8')

test('Final list and detail routes are registered and Live hands final games off', () => {
  assert.match(app, /path="\/final"/)
  assert.match(app, /path="\/final\/:game_pk"/)
  assert.match(livePage, /isFinal \? `\/final\/\$\{game\.game_pk\}`/)
})

test('Final detail renders team-grouped batting and pitching lines', () => {
  assert.match(finalPage, /<TeamBoxScore team=\{data\.boxscore\?\.away\} label="Away"/)
  assert.match(finalPage, /<TeamBoxScore team=\{data\.boxscore\?\.home\} label="Home"/)
  assert.match(finalPage, /Scoring plays/)
  assert.match(finalPage, /ABS tracker/)
})

test('primary ribbon uses grouped menus instead of every route as a top-level link', () => {
  assert.match(app, /label: 'Research'/)
  assert.match(app, /label: 'Markets'/)
  assert.match(app, /label: 'Reference'/)
  assert.match(app, /<NavLink to="\/final"/)
})

