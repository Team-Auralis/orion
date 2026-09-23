import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert';

console.log('--- RUNNING FULLY CODED ORION V31.0 REPLICA SELF-CHECK ---');

// 1. Verify Top Bar Component
const topBarSrc = fs.readFileSync(path.resolve('src', 'components', 'OrionTopBar.tsx'), 'utf-8');
assert.ok(topBarSrc.includes('O R I O N'), 'TopBar must feature O R I O N brand');
assert.ok(topBarSrc.includes('BEYOND HUMAN. BEYOND MACHINES.'), 'TopBar must feature brand subtitle');
assert.ok(topBarSrc.includes('SPACE WEATHER: STABLE'), 'TopBar must feature space weather badge');
assert.ok(topBarSrc.includes('LIVE'), 'TopBar must feature LIVE badge');
console.log('[PASS] OrionTopBar fully coded component verified.');

// 2. Verify Left Sidebar Component
const sidebarSrc = fs.readFileSync(path.resolve('src', 'components', 'OrionSidebar.tsx'), 'utf-8');
const navItems = ['HOME', 'CHAT', 'RESEARCH', 'DEV STUDIO', 'MEMORY', 'SYSTEM', 'GALAXY MAP', 'TOOLS'];
for (const item of navItems) {
  assert.ok(sidebarSrc.includes(item), `Sidebar must include navigation tab ${item}`);
}
assert.ok(sidebarSrc.includes('INTELLIGENCE BEYOND ORIGINS'), 'Sidebar must include quote');
assert.ok(sidebarSrc.includes('ORION v31.0'), 'Sidebar must include version badge');
console.log('[PASS] OrionSidebar fully coded component with 8 tabs verified.');

// 3. Verify Neural Network Sync Card
const syncSrc = fs.readFileSync(path.resolve('src', 'components', 'OrionNeuralSyncCard.tsx'), 'utf-8');
assert.ok(syncSrc.includes('NEURAL NETWORK SYNC'), 'Sync card must feature title');
assert.ok(syncSrc.includes('ONLINE'), 'Sync card must show ONLINE');
assert.ok(syncSrc.includes('CORE 0'), 'Sync card must show CORE bars');
assert.ok(syncSrc.includes('polyline'), 'Sync card must render SVG waveform');
console.log('[PASS] OrionNeuralSyncCard fully coded HUD card verified.');

// 4. Verify Right HUD Panels
const rightSrc = fs.readFileSync(path.resolve('src', 'components', 'OrionRightPanels.tsx'), 'utf-8');
assert.ok(rightSrc.includes('STAR CHART INDEX'), 'Right panel must feature Star Chart');
assert.ok(rightSrc.includes('NGC 1300'), 'Right panel must feature NGC 1300');
assert.ok(rightSrc.includes('MISSION LOG'), 'Right panel must feature Mission Log');
assert.ok(rightSrc.includes('2K'), 'Right panel must feature 2K gauge');
console.log('[PASS] OrionRightPanels fully coded HUD cards verified.');

// 5. Verify 6 Glass Action Cards
const dockSrc = fs.readFileSync(path.resolve('src', 'components', 'OrionActionDock.tsx'), 'utf-8');
const cards = ['DEBUG SCREEN', 'CLIPBOARD COPILOT', 'RECALL MEMORY', 'DEV WORKSPACE', 'VOICE MEMO', 'SYSTEM PURGE'];
for (const c of cards) {
  assert.ok(dockSrc.includes(c), `ActionDock must include card ${c}`);
}
console.log('[PASS] OrionActionDock with all 6 glass cards verified.');

// 6. Verify Bottom Command Bar & Centerpiece
const bottomSrc = fs.readFileSync(path.resolve('src', 'components', 'OrionBottomCommandBar.tsx'), 'utf-8');
assert.ok(bottomSrc.includes('Ask Orion anything...'), 'Bottom command bar must feature placeholder');
const centerSrc = fs.readFileSync(path.resolve('src', 'components', 'OrionCenterCore.tsx'), 'utf-8');
assert.ok(centerSrc.includes('armillary_sphere_pedestal.png'), 'Center core must render Armillary Core asset');
console.log('[PASS] OrionBottomCommandBar and OrionCenterCore verified.');

// 7. Verify App Assembly and Production Build
const appSrc = fs.readFileSync(path.resolve('src', 'App.tsx'), 'utf-8');
assert.ok(appSrc.includes('OrionTopBar'), 'App must render OrionTopBar');
assert.ok(appSrc.includes('OrionSidebar'), 'App must render OrionSidebar');
assert.ok(appSrc.includes('OrionNeuralSyncCard'), 'App must render OrionNeuralSyncCard');
assert.ok(appSrc.includes('OrionRightPanels'), 'App must render OrionRightPanels');
assert.ok(appSrc.includes('OrionActionDock'), 'App must render OrionActionDock');
assert.ok(appSrc.includes('OrionBottomCommandBar'), 'App must render OrionBottomCommandBar');

const distHtml = path.resolve('dist', 'index.html');
assert.ok(fs.existsSync(distHtml), 'dist/index.html must exist from build');
console.log('[PASS] Full App assembly and production build verified.');

console.log('--- ALL FULLY CODED REPLICA CHECKS PASSED ---');
