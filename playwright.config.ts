// playwright.config.ts
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  // Diretório onde os testes são procurados (pode ser a raiz do projeto)
  testDir: '.',
  testIgnore: ['**/WinSAT/**'],

  // Timeout padrão de cada teste
  timeout: 30_000,

  // Configurações que se aplicam a **todos** os projetos
  use: {
    trace: 'on',                 // grava trace de cada teste
    video: 'on',                 // grava vídeo de cada teste (ou use 'retain-on-failure')
    headless: true,              // opcional: roda browsers em modo headless
    // you can set other defaults here (baseURL, viewport, etc.)
  },

  // (Opcional) Executa o mesmo teste nos três navegadores principais
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox',  use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit',   use: { ...devices['Desktop Safari'] } },
  ],
});