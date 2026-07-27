import asyncio
import os
import json
import time
import re
import logging
from typing import Optional, Callable, List, Dict
from playwright.async_api import async_playwright, Page, BrowserContext, expect
from dotenv import load_dotenv

logger = logging.getLogger("CHEPBotEngine")

class CHEPBotEngine:
    def __init__(self, log_callback: Optional[Callable[[str], None]] = None):
        self.raw_log_cb = log_callback or (lambda msg: print(msg))
        self.playwright = None
        self.contexts: Dict[str, BrowserContext] = {}
        self.pages: Dict[str, Page] = {}
        self.load_env_vars()

    @property
    def page(self) -> Optional[Page]:
        if self.pages:
            for p in self.pages.values():
                if p and not p.is_closed():
                    return p
        return None

    def load_env_vars(self):
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)
        self.email_purm2 = os.getenv("CHEP_EMAIL_PURM2", "gabrielpeixoto@purm2.com.br")
        self.password_purm2 = os.getenv("CHEP_PASSWORD_PURM2", "")
        self.email_purm3 = os.getenv("CHEP_EMAIL_PURM3", "gabrielpeixoto@purm3.com.br")
        self.password_purm3 = os.getenv("CHEP_PASSWORD_PURM3", "")

    def log(self, message: str):
        msg_str = str(message)
        if "intercepts pointer events" in msg_str or "retrying click action" in msg_str:
            return
        if "Timeout" in msg_str and "exceeded" in msg_str:
            clean_msg = msg_str.split("Call log:")[0].strip()
            self.raw_log_cb(f"⚠️ {clean_msg[:120]}")
            return
        if len(msg_str) > 180 and "\n" in msg_str:
            msg_str = msg_str.split("\n")[0]
        self.raw_log_cb(msg_str)

    def get_credentials_for_profile(self, profile_name: str):
        self.load_env_vars()
        if "PURM3" in profile_name.upper():
            return self.email_purm3, self.password_purm3
        return self.email_purm2, self.password_purm2

    async def connect_cdp(self, cdp_url: str = "http://localhost:9222") -> bool:
        try:
            await self.get_browser_for_profile("BR__LH_PURM2")
            return True
        except Exception:
            return False

    async def launch_new_browser(self, headless: bool = True) -> bool:
        try:
            await self.get_browser_for_profile("BR__LH_PURM2", headless=headless)
            return True
        except Exception:
            return False

    async def get_browser_for_profile(self, profile_name: str, headless: bool = True) -> Page:
        """Navegador Chrome independente por perfil (PURM2 vs PURM3)"""
        clean_profile_id = "PURM3" if "PURM3" in profile_name.upper() else "PURM2"

        if clean_profile_id in self.pages and self.pages[clean_profile_id] and not self.pages[clean_profile_id].is_closed():
            page = self.pages[clean_profile_id]
            try:
                await page.bring_to_front()
                return page
            except Exception:
                pass

        self.log(f"🚀 Abrindo navegador para a conta {clean_profile_id}...")
        
        if not self.playwright:
            self.playwright = await async_playwright().start()

        user_data_dir = os.path.join(os.path.expanduser("~"), f".chep_bot_chrome_profile_{clean_profile_id.lower()}")
        os.makedirs(user_data_dir, exist_ok=True)

        context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
            viewport=None,
            no_viewport=True,
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--high-dpi-support=1",
                "--force-device-scale-factor=1"
            ]
        )

        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://cmaweb.chep.com/bluechat", wait_until="domcontentloaded")
        
        self.contexts[clean_profile_id] = context
        self.pages[clean_profile_id] = page

        await self.ensure_user_is_logged_in(page, profile_name)
        return page

    async def auto_login_if_needed(self, page: Page, profile_name: str = "BR__LH_PURM2"):
        """Sequência exata do Playwright test para login no Auth0"""
        try:
            url = page.url
            if "auth0.com" in url or "login" in url or "signin" in url:
                email, password = self.get_credentials_for_profile(profile_name)
                
                self.log(f"🔑 Login detectado! Preenchendo credenciais para {profile_name} ({email})...")
                
                # Suporte para login Auth0, Okta e Bluechat tradicional (placeholder='Your e-mail')
                email_input = page.locator("input[placeholder*='e-mail'], input[placeholder*='Your e-mail'], input[name='login'], input#login").first
                if not await email_input.is_visible(timeout=1500):
                    email_input = page.get_by_role('textbox', name='Email address')
                if not await email_input.is_visible(timeout=1500):
                    email_input = page.locator("input#username, input[name='username'], input[type='email']").first
                
                try:
                    await email_input.wait_for(state="visible", timeout=4000)
                    await email_input.click()
                    await email_input.fill(email)
                    await email_input.press("Tab")
                except Exception as e_em:
                    self.log(f"   ⚠️ Tentando preencher e-mail via locator direto: {e_em}")

                pass_input = page.locator("input[type='password'], input[name='password'], input#password").first
                if not await pass_input.is_visible(timeout=1500):
                    pass_input = page.get_by_role('textbox', name='Password')

                try:
                    await pass_input.wait_for(state="visible", timeout=4000)
                    await pass_input.click()
                    await pass_input.fill(password)
                    
                    # Botão Sign in ou Enter
                    btn_signin = page.locator("button:has-text('Sign in'), button:has-text('Log in'), button[type='submit']").first
                    if await btn_signin.is_visible(timeout=1500):
                        await btn_signin.click()
                    else:
                        await pass_input.press("Enter")
                except Exception as e_pass:
                    self.log(f"   ⚠️ Tentando submeter senha: {e_pass}")

                await asyncio.sleep(4)

        except Exception as e:
            self.log(f"⚠️ Aviso no login: {e}")

    async def ensure_user_is_logged_in(self, page: Page, profile_name: str = "BR__LH_PURM2") -> bool:
        await asyncio.sleep(1)
        target_email, _ = self.get_credentials_for_profile(profile_name)
        
        if "auth0.com" in page.url or "login" in page.url or "signin" in page.url:
            self.log(f"🔐 Autenticando {profile_name} ({target_email})...")
            await self.auto_login_if_needed(page, profile_name)
            await asyncio.sleep(3)
            
            if "auth0.com" not in page.url and "login" not in page.url and "signin" not in page.url:
                self.log(f"🟢 Login realizado com sucesso para {profile_name}!")
                return True

            for wait_sec in range(1, 20):
                if "auth0.com" not in page.url and "login" not in page.url and "signin" not in page.url:
                    self.log(f"🟢 Login concluído para {profile_name}!")
                    return True
                await asyncio.sleep(1)

            self.log(f"❌ Tela de login ainda ativa para {profile_name}. Verifique a senha no arquivo .env!")
            return False

        return True

    async def close(self):
        try:
            for ctx in self.contexts.values():
                await ctx.close()
            if self.playwright:
                await self.playwright.stop()
            self.log("🔒 Navegadores fechados.")
        except Exception:
            pass

    async def create_occurrence(
        self,
        delivery_number: str,
        note_type: str,
        description: str,
        priority: str = "HIGH",
        process_name: str = "LATAM - Brazil - Logistics",
        profile_name: str = "BR__LH_PURM2",
        attachment_path: Optional[str] = None,
        test_mode: bool = False
    ) -> bool:
        """Processo retornado para o fluxo original; preenchimento de nota com delay de carregamento e foco correto"""
        page = await self.get_browser_for_profile(profile_name)

        delivery_clean = delivery_number.strip()
        if not delivery_clean:
            return False

        try:
            self.log(f"\n🔍 [1/6] Pesquisando a Delivery #{delivery_clean} sob a conta {profile_name}...")
            
            if "bluechat" not in page.url:
                await page.goto("https://cmaweb.chep.com/bluechat", wait_until="domcontentloaded")
                await asyncio.sleep(2)

            if "auth0.com" in page.url or "login" in page.url:
                await self.ensure_user_is_logged_in(page, profile_name)
                await page.goto("https://cmaweb.chep.com/bluechat", wait_until="domcontentloaded")
                await asyncio.sleep(2)

            # 0. CARD HEADER (se estiver na home)
            card_header = page.locator('.cardWidget-header').first
            if await card_header.is_visible(timeout=1500):
                await card_header.click()
                await asyncio.sleep(1.5)

            # 1. FILTRO DE ENTREGA + ENTER + APPLY
            self.log(f"   -> Preenchendo '{delivery_clean}' no campo 'Número de entrega'...")
            
            deliv_input = page.locator('app-data-filter-multi-string-input').filter(has_text='Número de entrega').get_by_role('textbox')
            if not await deliv_input.is_visible(timeout=2000):
                deliv_input = page.locator("app-data-filter-multi-string-input input, input[placeholder*='entrega']").last

            if await deliv_input.is_visible(timeout=2500):
                await deliv_input.click(force=True)
                await deliv_input.fill("")
                await deliv_input.fill(delivery_clean)
                await deliv_input.press("Enter")
                self.log(f"   🟢 [OK] Número de entrega ({delivery_clean}) confirmado via Enter!")
                await asyncio.sleep(0.5)

                btn_apply = page.get_by_role('button', name=' Apply')
                if not await btn_apply.is_visible(timeout=1500):
                    btn_apply = page.get_by_role("button", name="Apply")
                if not await btn_apply.is_visible(timeout=1500):
                    btn_apply = page.locator("button:has-text('APPLY'), button:has-text('Apply')").first

                if await btn_apply.is_visible(timeout=2000):
                    await btn_apply.click(force=True)
                    self.log("   🟢 [OK] Clicado no botão Apply!")
                    await asyncio.sleep(2.5)

            modal = page.locator(".modal-content, .modal-dialog, [role='dialog'], div:has-text('Criação de notas')").last

            max_modal_attempts = 4
            modal_filled_success = False

            for attempt in range(1, max_modal_attempts + 1):
                self.log(f"\n⏳ [2/6] Verificando e abrindo a Modal (Tentativa {attempt}/{max_modal_attempts})...")
                
                is_modal_already_open = False
                try:
                    if await modal.is_visible(timeout=1500):
                        is_modal_already_open = True
                        self.log("📌 Modal 'Criação de notas' já está aberta na tela!")
                except Exception:
                    pass

                if not is_modal_already_open:
                    create_note_btn = page.get_by_role('button', name='Criar uma nota  ')
                    if not await create_note_btn.is_visible(timeout=2500):
                        create_note_btn = page.get_by_role("button", name="Criar uma nota")
                    if not await create_note_btn.is_visible(timeout=2500):
                        create_note_btn = page.locator("button:has-text('CRIAR UMA NOTA'), button:has-text('Criar uma nota')").last
                    
                    try:
                        await create_note_btn.click(timeout=15000)
                    except Exception:
                        await create_note_btn.click(force=True, timeout=15000)
                    
                    await asyncio.sleep(2.5)

                self.log("📝 [3/6] Clicando no Processo...")

                # 1. PROCESSO* (.ng-arrow-wrapper.first())
                arrow1 = modal.locator(".ng-arrow-wrapper").first
                if not await arrow1.is_visible(timeout=2000):
                    arrow1 = page.locator(".ng-arrow-wrapper").first

                await arrow1.click(force=True)
                await asyncio.sleep(0.8)

                opt_logistics = page.locator(".ng-option").filter(has_text="Logistics").first
                if not await opt_logistics.is_visible(timeout=1500):
                    opt_logistics = page.get_by_text("LATAM - Brazil - Logistics").first

                no_items = page.get_by_text("No items found")

                is_option_valid = False
                if await opt_logistics.is_visible(timeout=2000):
                    is_disabled = await opt_logistics.evaluate("el => el.classList.contains('ng-option-disabled') || el.getAttribute('aria-disabled') === 'true'")
                    if not is_disabled:
                        is_option_valid = True

                if is_option_valid and not await no_items.is_visible(timeout=500):
                    await opt_logistics.click(force=True)
                    self.log("   🟢 [OK] Processo definido para: 'LATAM - Brazil - Logistics'!")
                    modal_filled_success = True
                    break
                else:
                    self.log("   ⚠️ 'No items found' ou opção desabilitada! Clicando em '×Close' para fechar e tentar novamente...")
                    if attempt < max_modal_attempts:
                        close_x = page.get_by_text('×Close')
                        if not await close_x.is_visible(timeout=1000):
                            close_x = page.get_by_text('×')
                        if not await close_x.is_visible(timeout=1000):
                            close_x = modal.locator('.modal-header button.close, button.close, [aria-label="Close"]').first
                        
                        await close_x.click(force=True)
                        await asyncio.sleep(1.0)
                        try:
                            await create_note_btn.click(timeout=15000)
                        except Exception:
                            await create_note_btn.click(force=True, timeout=15000)
                        
                        await asyncio.sleep(2.5)

                    self.log("📝 [3/6] Clicando no Processo...")

                    # 1. PROCESSO* (.ng-arrow-wrapper.first())
                    arrow1 = modal.locator(".ng-arrow-wrapper").first
                    if not await arrow1.is_visible(timeout=2000):
                        arrow1 = page.locator(".ng-arrow-wrapper").first

                    await arrow1.click(force=True)
                    await asyncio.sleep(0.8)

                    opt_logistics = page.locator(".ng-option").filter(has_text="Logistics").first
                    if not await opt_logistics.is_visible(timeout=1500):
                        opt_logistics = page.get_by_text("LATAM - Brazil - Logistics").first

                    no_items = page.get_by_text("No items found")

                    is_option_valid = False
                    if await opt_logistics.is_visible(timeout=2000):
                        is_disabled = await opt_logistics.evaluate("el => el.classList.contains('ng-option-disabled') || el.getAttribute('aria-disabled') === 'true'")
                        if not is_disabled:
                            is_option_valid = True

                    if is_option_valid and not await no_items.is_visible(timeout=500):
                        await opt_logistics.click(force=True)
                        self.log("   🟢 [OK] Processo selecionado: 'LATAM - Brazil - Logistics'!")
                        await asyncio.sleep(0.5)
                        
                        # --- Clicar na seta para ABRIR novamente o dropdown de Processo ---
                        self.log("   🔽 Clicando na seta para abrir a aba de Processos novamente...")
                        await arrow1.click(force=True)
                        await asyncio.sleep(0.5)
                        
                        # --- Clicar na seta para FECHAR a aba de Processos ---
                        self.log("   🔼 Clicando na seta para fechar a aba de Processos...")
                        await arrow1.click(force=True)
                        await asyncio.sleep(0.5)
                        
                        # --- Pressionar TAB para mover o foco para o Tipo de Nota ---
                        self.log("   ⌨️ Pressionando TAB para mover o foco para Tipo de Nota...")
                        await page.keyboard.press('Tab')
                        await asyncio.sleep(0.5)

                        modal_filled_success = True
                        break
                    else:
                        self.log("   ⚠️ 'No items found' ou opção desabilitada! Clicando em '×Close' para fechar e tentar novamente...")
                        if attempt < max_modal_attempts:
                            close_x = page.get_by_text('×Close')
                            if not await close_x.is_visible(timeout=1000):
                                close_x = page.get_by_text('×')
                            if not await close_x.is_visible(timeout=1000):
                                close_x = modal.locator('.modal-header button.close, button.close, [aria-label="Close"]').first
                            
                            await close_x.click(force=True)
                            await asyncio.sleep(1.0)
                            try:
                                await modal.wait_for(state="hidden", timeout=3000)
                            except Exception:
                                pass
                            await asyncio.sleep(2.0)  # Cortina cinza sumir!
                        else:
                            self.log("❌ Limite de tentativas atingido.")

            # --- 1. Seleção do Tipo de Nota ---
            self.log(f"   -> Selecionando Tipo de Nota: '{note_type}'...")
            await self.abrirTipoNota(page, note_type)

            # --- 2. Seleção da Prioridade ---
            self.log("   -> Selecionando Prioridade: 'HIGH'...")
            await self.selecionarPrioridade(page, priority_name='HIGH')


            # TEXTO DA MENSAGEM (.ql-editor)
            self.log("   -> 4. Preenchendo mensagem no editor (.ql-editor)...")
            try:
                ql_editor = modal.locator('.ql-editor').first
                if not await ql_editor.is_visible(timeout=2000):
                    ql_editor = page.locator('.ql-editor').first
                
                await ql_editor.wait_for(state="visible", timeout=4000)
                await ql_editor.click(force=True)
                
                # Gera tags <p> individuais para cada linha não vazia, eliminando a margem do Quill via CSS inline
                lines = [l.strip() for l in description.replace('\r\n', '\n').split('\n') if l.strip()]
                html_formatted = "".join([f'<p style="margin: 0; padding: 0; line-height: 1.4;">{line}</p>' for line in lines])
                
                await ql_editor.evaluate("(el, html) => { el.innerHTML = html; el.dispatchEvent(new Event('input', { bubbles: true })); }", html_formatted)
                self.log("   🟢 [OK] Texto da mensagem preenchido no editor com espaçamento exato por linha!")
            except Exception as e_ed:
                self.log(f"   ⚠️ Inserindo via fallback: {e_ed}")
                try:
                    await page.locator('.ql-editor').first.click(force=True)
                    await page.keyboard.insert_text(description)
                except Exception:
                    pass

            # ANEXAR FOTO / ARQUIVO
            if attachment_path and os.path.exists(attachment_path):
                self.log(f"📎 [5/6] Anexando arquivo: {os.path.basename(attachment_path)}...")
                try:
                    # 1. Localiza o input de arquivo (mesmo que esteja invisível/escondido na modal)
                    file_input = modal.locator('input[type="file"]').first
                    if await file_input.count() == 0:
                        file_input = page.locator('input[type="file"]').first

                    if await file_input.count() > 0:
                        # Usa o método correto da API Python do Playwright: set_input_files
                        await file_input.set_input_files(attachment_path)
                        await asyncio.sleep(1.5)
                        self.log("   🟢 [OK] Arquivo anexado com sucesso via set_input_files!")
                    else:
                        # 2. Fallback via acionamento do botão 'Anexos'
                        anexo_btn = modal.get_by_text('Anexos').first
                        if await anexo_btn.is_visible(timeout=2000):
                            async with page.expect_file_chooser() as fc_info:
                                await anexo_btn.click(force=True)
                            file_chooser = await fc_info.value
                            await file_chooser.set_files(attachment_path)
                            await asyncio.sleep(1.5)
                            self.log("   🟢 [OK] Foto anexada via botão 'Anexos'!")
                except Exception as e_att:
                    self.log(f"   ⚠️ Falha ao anexar foto: {e_att}")
            else:
                self.log("📎 [5/6] Nenhum anexo de foto pendente para enviar.")

            # MODO TESTE (SEGURANÇA TOTAL: NENHUM CLIQUE EM SALVAR/CRIAR PEDIDO)
            if test_mode:
                self.log("\n🧪 [MODO TESTE ATIVO] Formulário preenchido com sucesso!")
                shots_dir = os.path.join(os.path.dirname(__file__), "screenshots")
                os.makedirs(shots_dir, exist_ok=True)
                fname = f"teste_{delivery_clean}_{int(time.time())}.png"
                shot_file = os.path.join(shots_dir, fname)
                await page.screenshot(path=shot_file)
                self.log(f"📸 Print de validação do teste: <a href='/screenshots/{fname}' target='_blank' style='color:#38bdf8; font-weight:bold; text-decoration:underline;'>🔍 Visualizar Print da Tela (#{delivery_clean})</a>")
                self.log("⛔ [SEGURANÇA] O botão 'CRIAR PEDIDO(S)' FOI OMITIDO e NÃO SERÁ CLICADO no Modo Teste!")
                return True

            # BOTÃO SALVAR / CRIAR PEDIDO(S) (EXECUTADO APENAS EM MODO REAL)
            self.log("💾 [6/6] Clicando no botão 'CRIAR PEDIDO(S)'...")
            save_btn = modal.locator("button:has-text('CRIAR PEDIDO(S)'), button:has-text('CRIAR PEDIDO'), button:has-text('Salvar'), button:has-text('CRIAR NOTA')").first
            if not await save_btn.is_visible(timeout=2000):
                save_btn = page.locator("button:has-text('CRIAR PEDIDO(S)'), button:has-text('CRIAR PEDIDO')").first

            if await save_btn.is_visible(timeout=3000):
                await save_btn.click(force=True)
                await asyncio.sleep(2.5)
                self.log(f"✅ Ocorrência '{note_type}' criada e enviada com sucesso no CHEP!")
                return True
            else:
                self.log("⚠️ Botão 'CRIAR PEDIDO(S)' não encontrado na tela!")

            return True

        except Exception as e:
            self.log(f"❌ Erro ao preencher ocorrência: {e}")
            return False

    async def respond_contact_site(
        self,
        delivery_number: str,
        message_text: str,
        profile_name: str = "BR__LH_PURM2",
        attachment_path: str = None,
        test_mode: bool = False
    ) -> str:
        return await self.create_contact_chep_response(delivery_number, message_text, profile_name, test_mode)

    async def create_contact_chep_response(
        self,
        delivery_number: str,
        reply_message: str,
        profile_name: str = "BR__LH_PURM2",
        test_mode: bool = False
    ) -> str:
        page = await self.get_browser_for_profile(profile_name)

        try:
            self.log(f"\n🌐 [2º Sistema] Abrindo Service Desk (contact.cmaweb.chep.com)...")
            
            contact_page = page
            if "contact.cmaweb.chep.com" not in contact_page.url:
                await contact_page.goto("https://contact.cmaweb.chep.com/workspaces/CHEP/dashboard", wait_until="domcontentloaded")
                await asyncio.sleep(2)

            is_logged = await self.ensure_user_is_logged_in(contact_page, profile_name)
            if not is_logged:
                return "ERROR"

            opened_btn = contact_page.locator("a[href*='requests'], a:has-text('Opened'), div:has-text('Note(s) Opened'), div:has-text('Opened'), button:has-text('Opened')").first
            if await opened_btn.is_visible(timeout=3000):
                await opened_btn.click()
                await asyncio.sleep(1.5)

            search_box = contact_page.locator("input[placeholder*='Search by delivery'], input[placeholder*='delivery number']").first
            if await search_box.is_visible(timeout=3000):
                await search_box.fill(delivery_number)
                await asyncio.sleep(0.5)
                search_btn = contact_page.locator("button:has-text('Search'), button:has-text('Pesquisar')").first
                if await search_btn.is_visible(timeout=2000):
                    await search_btn.click()
                else:
                    await search_box.press("Enter")
                await asyncio.sleep(2)

            table_rows = contact_page.locator("table tbody tr")
            await table_rows.first.wait_for(state="visible", timeout=6000)
            
            row_text = await table_rows.first.inner_text()
            row_lower = row_text.lower()
            if "pending carrier reply" in row_lower or ("carrier reply" in row_lower and "internal" not in row_lower):
                self.log("🚨 [ATENÇÃO] Status na tabela é 'Pending carrier reply' (Roxo)!")
                return "PENDING_CARRIER_REPLY"

            await table_rows.first.click()
            await asyncio.sleep(2)

            editor = contact_page.locator("[contenteditable='true'], textarea, .ql-editor, [placeholder*='Insert text here']").first
            await editor.wait_for(state="visible", timeout=5000)
            await editor.click()
            await editor.fill(reply_message)
            await asyncio.sleep(1)

            if test_mode:
                self.log("🧪 [MODO TESTE 2º SITE] Resposta preenchida! NÃO ENVIADA.")
                return "TEST_MODE_SUCCESS"

            send_btn = contact_page.locator("button:has(.fa-paper-plane), button:has-text('Send'), button.btn-primary:has(svg)").first
            if await send_btn.is_visible(timeout=3000):
                await send_btn.click()
                await asyncio.sleep(2)
                self.log("✅ Resposta enviada no Contact CHEP!")
                return "SUCCESS"
            return "SUCCESS"

        except Exception as e:
            self.log(f"❌ Erro no 2º site: {e}")
            return "ERROR"

    async def check_pending_carrier_replies(self, daily_deliveries: List[str], profile_name: str = "BR__LH_PURM2") -> List[str]:
        page = await self.get_browser_for_profile(profile_name)

        answered_deliveries = []
        try:
            self.log(f"🔍 [Monitor] Verificando {len(daily_deliveries)} deliveries no Service Desk ({profile_name})...")
            
            contact_page = page
            target_url = "https://contact.cmaweb.chep.com/workspaces/CHEP/requests?page=0&step=10"
            if "contact.cmaweb.chep.com" not in contact_page.url:
                await contact_page.goto(target_url, wait_until="domcontentloaded")
                await asyncio.sleep(2)

            is_logged = await self.ensure_user_is_logged_in(contact_page, profile_name)
            if not is_logged:
                self.log("❌ Falha no login do Contact CHEP.")
                return []

            search_box = contact_page.locator("input[placeholder*='Search by delivery'], input[placeholder*='delivery number']").first
            
            try:
                await search_box.wait_for(state="visible", timeout=4000)
            except Exception:
                self.log("📌 Carregando tela de lista de solicitações...")
                await contact_page.goto(target_url, wait_until="domcontentloaded")
                await asyncio.sleep(2)
                await search_box.wait_for(state="visible", timeout=8000)

            self.log(f"🟢 Pronto para pesquisar sob a conta {profile_name}!")

            for deliv in daily_deliveries:
                deliv_clean = deliv.strip()
                if not deliv_clean:
                    continue

                self.log(f"   -> Pesquisando delivery #{deliv_clean} no perfil {profile_name}...")
                await search_box.click()
                await search_box.fill(deliv_clean)
                await asyncio.sleep(0.3)
                
                search_btn = contact_page.locator("button:has-text('Search'), button:has-text('Pesquisar')").first
                if await search_btn.is_visible(timeout=1500):
                    await search_btn.click()
                else:
                    await search_box.press("Enter")
                
                await asyncio.sleep(2.5)

                table_rows = contact_page.locator("table tbody tr")
                count = await table_rows.count()
                
                if count == 0:
                    self.log(f"🟡 Delivery #{deliv_clean}: Nenhuma nota encontrada no perfil {profile_name} (0 resultados).")
                    continue

                has_purple_reply = False
                for i in range(count):
                    row_text = await table_rows.nth(i).inner_text()
                    row_lower = row_text.lower()
                    
                    if "no results" in row_lower or "0 results" in row_lower:
                        continue

                    if "pending carrier reply" in row_lower or ("carrier reply" in row_lower and "internal" not in row_lower):
                        has_purple_reply = True
                        break

                if has_purple_reply:
                    self.log(f"🚨 [RESPONDIDA PELA CHEP] Delivery #{deliv_clean} possui status ROXO (Pending carrier reply)!")
                    answered_deliveries.append(deliv_clean)
                else:
                    self.log(f"🟡 Delivery #{deliv_clean}: Status na tabela é Amarelo (Pending internal reply).")

            if not answered_deliveries:
                self.log("🟢 Nenhuma nova resposta roxa encontrada.")
            
            return answered_deliveries

        except Exception as e:
            self.log(f"⚠️ Erro ao monitorar: {e}")
            return []

    async def abrirTipoNota(self, page, note_type: str):
        """Preenche o tipo de nota com esperas de renderização do Angular e seleção na lista."""
        try:
            # 1. Identifica o ng-select do Tipo de nota
            note_select = page.locator('ng-select[name="noteType"]')
            
            # 2. Garante que o campo terminou de carregar/habilitar após a seleção do processo
            await note_select.wait_for(state="visible", timeout=10000)
            
            # Se houver um atributo 'disabled' ou classe que impeça, podemos aguardar o input interno ficar ativo:
            input_el = note_select.locator('input')
            await input_el.wait_for(state="attached", timeout=5000)
            
            # 3. Clica e digita o tipo de nota com delay para o Angular processar
            self.log(f"   ⌨️ Clicando e digitando tipo de nota com delay: '{note_type}'")
            await input_el.click()
            await input_el.fill("") # Limpa se houver algo
            await input_el.type(note_type, delay=100)
            
            # 4. Aguarda a opção aparecer no dropdown e clica nela
            dropdown_panel = page.locator('.ng-dropdown-panel')
            await dropdown_panel.wait_for(state="visible", timeout=5000)
            
            opcao = dropdown_panel.locator('.ng-option', has_text=note_type)
            await opcao.wait_for(state="visible", timeout=3000)
            await opcao.click()
            
            self.log(f"   🟢 [OK] Tipo de Nota '{note_type}' selecionado com sucesso!")
        except Exception as e:
            self.log(f"   ⚠️ Falha ao selecionar Tipo de Nota '{note_type}': {e}")

    async def selecionarPrioridade(self, page, priority_name: str = "HIGH"):
        """Preenche o campo de Prioridade utilizando seletores diretos name='priority' e formcontrolname='priority'."""
        try:
            # 1. Busca primeiro pelos atributos nativos do Angular ng-select da Prioridade
            priority_select = page.locator('ng-select[name="priority"], ng-select[formcontrolname="priority"]').first
            
            if not await priority_select.is_visible(timeout=1500):
                # Fallback: busca pelo contêiner com o rótulo "Prioridade"
                priority_select = page.locator('div, fieldset, app-form-field').filter(has_text='Prioridade').locator('ng-select').first

            if not await priority_select.is_visible(timeout=1500):
                priority_select = page.locator('ng-select').filter(has_text='Prioridade').first

            await priority_select.wait_for(state="visible", timeout=4000)
            
            # 2. Clica no componente para abrir a lista
            input_el = priority_select.locator('input')
            if await input_el.is_visible(timeout=1500):
                await input_el.click()
            else:
                await priority_select.locator('.ng-arrow-wrapper').first.click(force=True)

            await asyncio.sleep(0.4)

            # 3. Clica na opção exata (ex: HIGH / NOT_DEFINE)
            opcao = page.locator('.ng-dropdown-panel .ng-option').filter(has_text=priority_name).first
            if await opcao.is_visible(timeout=2500):
                await opcao.click(force=True)
            else:
                # Digita o texto e envia Enter
                await input_el.fill(priority_name)
                await input_el.press('Enter')

            self.log(f"   🟢 [OK] Prioridade '{priority_name}' selecionada com sucesso!")
        except Exception as e:
            self.log(f"   ⚠️ Falha ao selecionar Prioridade '{priority_name}': {e}")

