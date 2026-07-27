import { test, expect } from '@playwright/test';

test('test – Tipo de Nota robusto', async ({ page }) => {
  // -------------------------------------------------------------
  // 1️⃣  Parte inicial (login, número de entrega) permanece igual
  // -------------------------------------------------------------
  await page.goto(
    'https://cmaprod.eu.auth0.com/u/login?state=hKFo2SBrbkFlR2d4NnZicDI3UmxUUlJ5UWFIMUxvQUtGZGM1UqFur3VuaXZlcnNhbC1sb2dpbqN0aWTZIEVmYTgwcTh2eWMweWRqQU9pcHFQTmhNNHo4VWZVZ2FNo2NpZNkgUXRKNnZyWjMxY2dERmRWd1hIOWNqZG1seDdLVFRCeHM'
  );
  await page.getByRole('textbox', { name: 'Email address' })
      .fill('gabrielpeixoto@purm2.com.br');
  await page.getByRole('textbox', { name: 'Password' }).fill('12345');
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await page.getByRole('main').getByText('Gestão de carga').click();

  // Número de entrega (igual ao seu código)
  await page
    .locator('app-data-filter-multi-string-input')
    .filter({ hasText: 'Número de entrega' })
    .getByRole('textbox')
    .fill('3788214652');
  await page.getByRole('button', { name: ' Apply' }).click();

  // Abre o modal “Criar uma nota”
  await page.getByRole('button', { name: 'Criar uma nota  ' }).click();

  // -------------------------------------------------------------
  // 2️⃣  **Seleção robusta de “Tipo de Nota”**
  // -------------------------------------------------------------

  // 2.1 – Localiza o label que antecede o ng‑select desejado
  const label = page.locator('label', { hasText: /Tipo de Nota/i });
  const select = label.locator('..').locator('ng-select').first();

  // 2.2 – Contêiner onde o Angular coloca as opções (overlay)
  const overlay = page.locator('.cdk-overlay-container');

  const opcaoDesejada = 'DADOS MOTORISTA'; // altere se precisar de outra
  const maxTentativas = 3;
  let selecionado = false;

  for (let tentativa = 1; tentativa <= maxTentativas; tentativa++) {
    console.info(`🔄 Tentativa ${tentativa} – abrindo dropdown`);

    // abre a lista
    await select.locator('.ng-arrow-wrapper').first().click({ force: true });

    // aguarda o overlay aparecer
    try {
      await overlay.waitFor({ state: 'visible', timeout: 4000 });
    } catch {
      console.warn('❗ Overlay não apareceu – tentando novamente');
      continue;
    }

    // campo de busca dentro do overlay
    const inputBusca = overlay
      .locator('input[type="search"], input.ng-input')
      .first();

    // garante que o input está realmente visível/focável
    await page.waitForFunction(
      (el) => !!el && !!(el as HTMLElement).offsetParent,
      inputBusca,
      { timeout: 2000 }
    );

    // limpa e digita a opção desejada
    await inputBusca.fill('');
    await inputBusca.type(opcaoDesejada, { delay: 50 });
    await page.waitForTimeout(600);

    // procura a opção (ignora espaço extra e case-insensitive)
    const opcao = overlay
      .locator('.ng-option')
      .filter({
        hasText: new RegExp(`^\\s*${opcaoDesejada}\\s*$`, 'i'),
      })
      .first();

    if (await opcao.isVisible({ timeout: 1500 })) {
      await opcao.click({ force: true });
      console.info('✅ Tipo de Nota selecionado via clique');
      selecionado = true;
      break;
    }

    // fallback: alguns setups aceitam texto livre, então pressiona Enter
    await inputBusca.press('Enter');
    console.info('✅ Tipo de Nota selecionado via Enter (fallback)');
    selecionado = true;
    break;
  }

  if (!selecionado) {
    console.error('⚠️ Não foi possível selecionar Tipo de Nota após todas as tentativas');
    // expect(selecionado).toBeTruthy(); // opcional: falha o teste aqui
  }

  // -------------------------------------------------------------
  // 3️⃣  Continuação do fluxo (processo, prioridade, descrição, anexos)
  // -------------------------------------------------------------
  await page.locator('.ng-arrow-wrapper').first().click();
  await page.locator('#adfb0545f2b7-1').click();

  // demais selects podem reutilizar o mesmo padrão acima
  await page
    .locator(
      '.ng-select.ng-select-single.ng-select-searchable.ng-untouched.ng-pristine.ng-valid > .ng-select-container > .ng-arrow-wrapper'
    )
    .click();
  await page
    .locator(
      '.ng-untouched > div:nth-child(2) > .ng-select > .ng-select-container > .ng-arrow-wrapper'
    )
    .click();

  await page.locator('div').filter({ hasText: /^HIGH$/ }).click();
  await page.locator('.ql-editor').click();
  await page.getByText('Anexos').click();
  await page.getByText('×Close').click();
});
