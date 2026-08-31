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
        self.approval_state = {"event": None, "action": None, "image_url": None, "delivery": None}
        self.current_searched_delivery: Dict[str, str] = {}
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
        self.password_purm2 = os.getenv("CHEP_PASSWORD_PURM2", "12345")
        self.email_purm3 = os.getenv("CHEP_EMAIL_PURM3", "gabrielpeixoto@purm3.com.br")
        self.password_purm3 = os.getenv("CHEP_PASSWORD_PURM3", "12345")

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

    async def save_debug_screenshot(self, page: Page, name: str, label: str):
        try:
            # Aguarda a renderização completa antes de tirar o print
            await page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass

        try:
            shots_dir = os.path.join(os.path.dirname(__file__), "static")
            os.makedirs(shots_dir, exist_ok=True)
            fname = f"{name}.png"
            shot_file = os.path.join(shots_dir, fname)
            await page.screenshot(path=shot_file)
            self.log(f"📸 [{label}]: <a href='/static/{fname}' target='_blank' style='color:#38bdf8; font-weight:bold; text-decoration:underline;'>Visualizar {name}.png</a>")
        except Exception as e:
            self.log(f"⚠️ Erro ao salvar print {name}: {e}")

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

    async def launch_new_browser(self, headless: bool = None) -> bool:
        if headless is None:
            headless = os.getenv("RENDER") is not None
        try:
            await self.get_browser_for_profile("BR__LH_PURM2", headless=headless)
            return True
        except Exception:
            return False

    async def get_browser_for_profile(self, profile_name: str, headless: bool = None, site_type: str = "cma", retry: int = 0) -> Page:
        if headless is None:
            headless = os.getenv("RENDER") is not None

        actual_site_type = "service_desk" if "service_desk" in site_type else "cma"

        # Se for o monitoramento (service_desk), força modo silencioso (headless) e isola o perfil
        if actual_site_type == "service_desk":
            headless = True
            clean_profile_id = "PURM3_MONITOR" if "PURM3" in profile_name.upper() else "PURM2_MONITOR"
        else:
            clean_profile_id = "PURM3" if "PURM3" in profile_name.upper() else "PURM2"

        page_key = f"{clean_profile_id}_{actual_site_type}"

        if page_key in self.pages:
            try:
                # Teste rápido de liveness
                await asyncio.wait_for(self.pages[page_key].evaluate("1+1"), timeout=3.0)
                return self.pages[page_key]
            except Exception:
                del self.pages[page_key]

        try:
            if not self.playwright:
                self.playwright = await async_playwright().start()

            user_data_dir = os.path.join(os.path.expanduser("~"), f".chep_bot_chrome_profile_{clean_profile_id.lower()}")
            os.makedirs(user_data_dir, exist_ok=True)

            viewport_cfg = {"width": 1920, "height": 1080} if headless else None
            
            args = [
                "--disable-blink-features=AutomationControlled",
                "--high-dpi-support=1",
                "--force-device-scale-factor=1"
            ]
            if headless:
                args.append("--window-size=1920,1080")
            else:
                args.append("--start-maximized")

            if clean_profile_id in self.contexts and self.contexts[clean_profile_id]:
                context = self.contexts[clean_profile_id]
                try:
                    if len(context.pages) > 0:
                        await asyncio.wait_for(context.pages[0].evaluate("1+1"), timeout=5.0)
                except Exception as e:
                    self.log(f"⚠️ [TIMEOUT] Navegador existente travou ou não responde. Recriando contexto... ({e})")
                    try: await context.close()
                    except: pass
                    self.contexts[clean_profile_id] = None
                    context = None
            else:
                context = None
                
            if context is None:
                # Remove a pasta de sessoes para impedir que o Chrome restaure abas órfãs
                import shutil
                sessions_dir = os.path.join(user_data_dir, "Default", "Sessions")
                if os.path.exists(sessions_dir):
                    try:
                        shutil.rmtree(sessions_dir)
                    except:
                        pass
                
                # Cada perfil tem seu próprio contexto isolado — NÃO encerra outros perfis
                # O user_data_dir já é único por perfil (purm2 / purm3), garantindo isolamento total
                context = await self.playwright.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=headless,
                    viewport=viewport_cfg,
                    no_viewport=not headless,
                    args=args
                )
                self.contexts[clean_profile_id] = context

            self.log("✅ [LOG] Navegador instanciado com sucesso.")
            self.log(f"🌐 [LOG] Navegando para a URL do {site_type}...")

            try:
                # O usuário pediu ESTRITAMENTE apenas 2 abas.
                # Aba 0: CMA Web
                # Aba 1: Service Desk
                
                if actual_site_type == "cma":
                    page = context.pages[0]
                else:
                    # Se for Service Desk, usamos a segunda aba. Se não existir, criamos.
                    if len(context.pages) < 2:
                        page = await context.new_page()
                    else:
                        page = context.pages[1]
                
                # Fecha qualquer aba extra (além de 2) que tenha ficado órfã
                extra_pages = context.pages[2:]
                for p in extra_pages:
                    try:
                        await p.close()
                    except:
                        pass
                
                self.pages[page_key] = page
                
                try:
                    await page.bring_to_front()
                except:
                    pass
                
                target_url = "https://contact.cmaweb.chep.com/workspaces/CHEP/requests?page=0&step=10" if "service_desk" in actual_site_type else "https://cmaweb.chep.com/"
                
                # Só navega se a URL atual não for o domínio alvo
                current_url = page.url
                needs_nav = True
                if "service_desk" in actual_site_type and "workspaces/CHEP/requests" in current_url:
                    needs_nav = False
                elif "service_desk" not in actual_site_type and "cmaweb.chep.com" in current_url and "workspaces" not in current_url:
                    needs_nav = False
                    
                if needs_nav:
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                
            except Exception as e:
                err_msg = str(e).lower()
                if "closed" in err_msg or "target page" in err_msg or "timeout" in err_msg:
                    self.log(f"⚠️ Erro de contexto/aba detectado: {e}. Recriando contexto limpo do zero...")
                    try: await context.close()
                    except: pass
                    self.contexts[clean_profile_id] = None
                    if page_key in self.pages: del self.pages[page_key]
                    
                    if retry >= 2:
                        self.log(f"[ERRO] Falha ao conectar ao {profile_name} após 3 tentativas. Cancelando ciclo.")
                        raise Exception(f"Falha ao conectar ao {profile_name} após 3 tentativas.")
                    
                    return await self.get_browser_for_profile(profile_name, headless, site_type, retry=retry + 1)
                else:
                    self.log(f"⚠️ Erro no carregamento da página {site_type}: {e}")
                    raise e
            
            self.pages[page_key] = page
            await self.ensure_user_is_logged_in(page, profile_name)
            return page
            
        except Exception as e:
            self.log(f"⚠️ ERRO FATAL AO CRIAR NAVEGADOR: {e}")
            raise e
        
    async def is_on_login_page(self, page: Page) -> bool:
        """Verifica rigorosamente se a página atual é a tela de login/autenticação"""
        url = page.url.lower()
        if any(k in url for k in ["login", "signin", "auth0", "okta", "b2c", "auth", "authorize"]):
            return True
            
        try:
            if await page.locator("text=/log in|welcome|continue with okta/i").first.is_visible(timeout=1000):
                return True
        except:
            pass

        try:
            if await page.get_by_role('textbox', name='Email address').is_visible(timeout=1000):
                return True
        except:
            pass

        try:
            email_field = page.locator("input[name='username'], input[name='identifier'], input[name='email'], input[type='email'], input#username").first
            if await email_field.is_visible(timeout=1000):
                return True
        except:
            pass

        return False

    async def auto_login_if_needed(self, page: Page, profile_name: str = "BR__LH_PURM2"):
        """Navegação e preenchimento de login com suporte Okta/Auth0/CHEP"""
        try:
            email, password = self.get_credentials_for_profile(profile_name)
            
            # 1. Procura o campo de e-mail com seletores abrangentes
            email_input = page.locator("input[placeholder*='e-mail'], input[placeholder*='Your e-mail'], input[placeholder*='e-mail'], input[name='login'], input#login, input[name='username'], input[name='identifier'], input[name='email'], input[type='email']").first
            if not await email_input.is_visible(timeout=1500):
                email_input = page.get_by_role('textbox', name='Email address')
            if not await email_input.is_visible(timeout=1500):
                email_input = page.get_by_placeholder("Your e-mail")

            if await email_input.is_visible(timeout=3000):
                self.log(f"🔑 Tela de login identificada! Efetuando login para {profile_name} ({email})...")
                await email_input.click(force=True)
                await email_input.fill("")
                await email_input.fill(email)

                # 2. Preenche a senha
                pass_input = page.locator("input[placeholder*='password'], input[placeholder*='Your password'], input[name='password'], input[type='password']").first
                if not await pass_input.is_visible(timeout=1500):
                    pass_input = page.get_by_placeholder("Your password")
                if not await pass_input.is_visible(timeout=1500):
                    pass_input = page.get_by_role('textbox', name='Password')

                if await pass_input.is_visible(timeout=3000):
                    if not password:
                        self.log(f"⚠️ ATENÇÃO: A senha do perfil {profile_name} está VAZIA! Defina CHEP_PASSWORD_{'PURM3' if 'PURM3' in profile_name else 'PURM2'} no .env ou no Render.")
                    
                    await pass_input.click(force=True)
                    await pass_input.fill("")
                    await pass_input.fill(password)
                    await asyncio.sleep(0.5)
                else:
                    self.log("⚠️ Campo de senha não encontrado na tela de login!")

                # 3. Submete o formulário clicando em Sign in / Continue ou Enter
                btn_submit = page.locator("button:has-text('Sign in'), button:has-text('Log in'), button:has-text('Continue'), input[value='Continue'], button[type='submit'], input[type='submit']").first
                if await btn_submit.is_visible(timeout=2000):
                    await btn_submit.click(force=True)
                elif await pass_input.is_visible():
                    await pass_input.press("Enter")
                
                await asyncio.sleep(4)

        except Exception as e:
            self.log(f"⚠️ Aviso no processo de login: {e}")

    async def ensure_user_is_logged_in(self, page: Page, profile_name: str = "BR__LH_PURM2") -> bool:
        await asyncio.sleep(1.5)
        target_email, _ = self.get_credentials_for_profile(profile_name)
        
        # 1. Se estiver na tela de login, executa auto_login_if_needed
        if await self.is_on_login_page(page):
            self.log(f"🔐 Autenticando {profile_name} ({target_email})...")
            await self.auto_login_if_needed(page, profile_name)
            await asyncio.sleep(3)
            
            for wait_sec in range(1, 25):
                if not await self.is_on_login_page(page):
                    self.log(f"🟢 Login concluído para {profile_name}!")
                    break
                await asyncio.sleep(1)

        # 2. Se a página atual for a HOME (/home), acessa a 'Gestão de carga'
        card_gestao = page.locator(".cardWidget-header").filter(has_text="Gestão de carga").first
        is_home_url = "home" in page.url
        is_card_visible = False
        try:
            is_card_visible = await card_gestao.is_visible(timeout=2000)
        except:
            pass

        if is_home_url or is_card_visible:
            self.log("🏠 Posição atual: Tela HOME. Acessando 'Gestão de carga'...")
            if is_card_visible:
                await card_gestao.click()
                await asyncio.sleep(2.5)
                await self.save_debug_screenshot(page, "debug_03_gestao_carga", "Print 3 - Gestão de Carga")
            else:
                await page.goto("https://cmaweb.chep.com/", wait_until="domcontentloaded")
                await asyncio.sleep(2)

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

    async def set_approval_event(self):
        if self.approval_state and self.approval_state.get("event"):
            self.approval_state["event"].set()

    async def create_occurrence(
        self,
        delivery_number: str,
        note_type: str,
        description: str,
        priority: str = "HIGH",
        process_name: str = "LATAM - Brazil - Logistics",
        profile_name: str = "BR__LH_PURM2",
        attachment_path: Optional[str] = None
    ) -> bool:
        """Processo retornado para o fluxo original; preenchimento de nota com delay de carregamento e foco correto"""
        self.is_creating_occurrence = True
        page = await self.get_browser_for_profile(profile_name)

        delivery_clean = delivery_number.strip()
        if not delivery_clean:
            return False

        try:
            self.log(f"\n🔐 [Passo 1/2] Verificando Autenticação e Gestão de Carga para a conta {profile_name}...")
            
            if "cmaweb.chep.com" not in page.url:
                await page.goto("https://cmaweb.chep.com/", wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(1.5)

            # Sempre garante o Login e a entrada na Gestão de Carga ANTES de pesquisar
            await self.ensure_user_is_logged_in(page, profile_name)

            card_header = page.locator('.cardWidget-header').first
            if await card_header.is_visible(timeout=1500):
                await card_header.click()
                await asyncio.sleep(2)

            # OTIMIZAÇÃO: Verifica se a Delivery já está filtrada e visível na tela
            clean_profile_id = "PURM3" if "PURM3" in profile_name.upper() else "PURM2"
            page_key = f"{clean_profile_id}_cma"
            btn_criar_nota_test = page.get_by_role("button", name="CRIAR UMA NOTA")

            is_already_searched = False
            try:
                if self.current_searched_delivery.get(page_key) == delivery_clean:
                    if await btn_criar_nota_test.is_visible(timeout=1000):
                        is_already_searched = True
                        self.log(f"⚡ [OTIMIZAÇÃO] Delivery #{delivery_clean} já está pesquisada na tela! Prosseguindo direto para a modal...")
            except Exception:
                pass

            if not is_already_searched:
                self.log(f"\n🟢 [Passo 2/2] Pesquisando a Delivery #{delivery_clean} na Gestão de Carga...")
                
                try:
                    await page.bring_to_front()
                except:
                    pass

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
                        self.current_searched_delivery[page_key] = delivery_clean

            # --- CHECAGEM RIGOROSA DE "0 Entregas selecionadas" LOGO APÓS A PESQUISA ---
            zero_locator = page.locator("text=/0\\s+entregas\\s+selecionadas/i").first
            btn_exists = page.locator("button, a").filter(has_text="CRIAR UMA NOTA")
            
            try:
                if await zero_locator.is_visible(timeout=1500) or (await btn_exists.count() == 0 and not await page.locator(".modal-content").is_visible(timeout=500)):
                    if await zero_locator.is_visible(timeout=500) or await btn_exists.count() == 0:
                        self.log(f"   ❌ ERRO: A Delivery #{delivery_clean} NÃO EXISTE no perfil {profile_name} (0 Entregas selecionadas).")
                        self.current_searched_delivery[page_key] = None
                        return "ZERO_ENTREGAS"
            except Exception:
                pass

            modal = page.locator(".modal-content").filter(has_text="Criação de notas").first

            max_modal_attempts = 8
            modal_ready = False

            for attempt in range(1, max_modal_attempts + 1):
                self.log(f"\n⏳ [2/6] Verificando e abrindo a Modal (Tentativa {attempt}/{max_modal_attempts})...")
                
                # --- VERIFICAÇÃO DE "0 Entregas selecionadas" NO LOOP ---
                try:
                    if await zero_locator.is_visible(timeout=500):
                        self.log(f"   ❌ ERRO: A Delivery #{delivery_clean} NÃO EXISTE no perfil {profile_name} (0 Entregas selecionadas).")
                        self.current_searched_delivery[page_key] = None
                        return "ZERO_ENTREGAS"
                except Exception:
                    pass
                
                is_modal_already_open = False
                try:
                    if await modal.is_visible(timeout=1000):
                        is_modal_already_open = True
                        self.log("📌 Modal 'Criação de notas' já está aberta na tela!")
                except Exception:
                    pass

                if not is_modal_already_open:
                    self.log(f"   ⏱️ Abrindo modal para Entrega #{delivery_clean}...")

                    # Tenta clicar diretamente no botão azul "CRIAR UMA NOTA" da entrega
                    modal_opened = False
                    
                    # Estratégia 1: botão "CRIAR UMA NOTA" direto (mais confiável)
                    btn_candidates = [
                        page.get_by_role("button", name="CRIAR UMA NOTA"),
                        page.get_by_role("button", name="Criar uma nota"),
                        page.locator("button.btn-primary:has-text('CRIAR')"),
                        page.locator("a.btn:has-text('CRIAR')"),
                        page.locator("[class*='btn']:has-text('CRIAR UMA NOTA')"),
                        page.locator("button, a").filter(has_text="CRIAR UMA NOTA").last,
                        page.locator("button, a").filter(has_text="Criar uma nota").last,
                    ]

                    for btn in btn_candidates:
                        try:
                            if await btn.is_visible(timeout=800):
                                await btn.scroll_into_view_if_needed()
                                await btn.click(force=True)
                                self.log("   ✅ Botão 'CRIAR UMA NOTA' clicado!")
                                break
                        except:
                            continue

                    await self.save_debug_screenshot(page, "debug_05_botao_criar_nota", "Print 5 - Botão Criar Nota")
                    await asyncio.sleep(1)

                # Aguarda visibilidade da Modal — se não abriu, volta ao topo do loop
                modal_abriu = False
                try:
                    await modal.wait_for(state="visible", timeout=4000)
                    modal_abriu = True
                except Exception:
                    pass

                await self.save_debug_screenshot(page, "debug_06_modal_aberta", "Print 6 - Modal Aberta")

                if not modal_abriu:
                    self.log(f"   ⚠️ Modal não abriu na tentativa {attempt}! Tentando novamente...")
                    # Fecha qualquer popup que possa estar bloqueando e tenta de novo
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.5)
                    continue

                # 2. SELEÇÃO DO PROCESSO* (com verificação de estado bloqueado/cinza e retry instantâneo)
                try:
                    proc_select = modal.locator("ng-select").first
                    # Modal confirmada aberta - aguarda até 5s para o ng-select renderizar
                    if not await proc_select.is_visible(timeout=5000):
                        self.log("   ⚠️ Modal abriu mas ng-select não apareceu em 5s. Fechando e repetindo...")
                        await page.keyboard.press("Escape")
                        await asyncio.sleep(0.5)
                        continue

                    # Aguarda até 3 segundos para o campo "Processo" carregar os dados do servidor
                    chip_loaded = False
                    is_disabled = False
                    val_text_init = ""
                    
                    for _ in range(6):
                        class_attr = await proc_select.get_attribute("class", timeout=1000) or ""
                        is_disabled = "ng-select-disabled" in class_attr
                        val_text_init = await proc_select.inner_text(timeout=500)
                        
                        # Se não está desativado E já tem algum valor preenchido, carregou!
                        if not is_disabled and ("LATAM" in val_text_init or "Logistics" in val_text_init or await proc_select.locator(".ng-value").count() > 0):
                            chip_loaded = True
                            break
                        await asyncio.sleep(0.5)
                    
                    if is_disabled:
                        # Campo travado/cinza - fechar e reabrir
                        if attempt < max_modal_attempts:
                            self.log(f"   ⚠️ [RETRY RÁPIDO] Chip cinza na tentativa {attempt}/{max_modal_attempts}! Refazendo...")
                            close_btn = modal.locator("button.close, .modal-header .close, button:has-text('Cancelar'), button:has-text('Close'), .close").first
                            if await close_btn.is_visible(timeout=1000):
                                await close_btn.click(force=True)
                            else:
                                await page.keyboard.press("Escape")
                            await asyncio.sleep(0.3)
                            continue
                        else:
                            self.log(f"   ⚠️ Limite de {max_modal_attempts} tentativas! Tentando forçar...")
                    else:
                        if chip_loaded:
                            self.log(f"   🟢 [OK] Modal carregada e chip já ativo pelo sistema! (Tentativa {attempt}/{max_modal_attempts})")
                        else:
                            self.log(f"   🟢 [OK] Modal carregada (chip vazio, vamos preencher). (Tentativa {attempt}/{max_modal_attempts})")
                        
                        # ---- PASSO 3: Preenche Processo e Tipo de Nota (dentro do loop para poder tentar de novo se falhar) ----
                        self.log("📝 [3/6] Preenchendo Processo e Tipo de Nota...")
                        
                        if not chip_loaded:
                            self.log("   -> Chip vazio, abrindo menu de Processo...")
                            await proc_select.scroll_into_view_if_needed()
                            
                            arrow = proc_select.locator(".ng-arrow-wrapper").first
                            if await arrow.is_visible(timeout=1000):
                                await arrow.click(force=True)
                            else:
                                await proc_select.click(force=True)
                                
                            await asyncio.sleep(0.5)

                            inp = proc_select.locator("input").first
                            if await inp.is_visible(timeout=1500):
                                await inp.click(force=True)
                                await inp.fill("Logistics")
                            else:
                                await page.keyboard.type("Logistics", delay=80)

                            await asyncio.sleep(0.8)

                            opt_log = page.locator(".ng-dropdown-panel .ng-option, ng-dropdown-panel .ng-option").filter(has_text="Logistics").first
                            if await opt_log.is_visible(timeout=2000):
                                await opt_log.click(force=True)
                            else:
                                await page.keyboard.press("Enter")

                            await asyncio.sleep(0.8)

                            val_text = await proc_select.inner_text()
                            if "Logistics" not in val_text and "LATAM" not in val_text:
                                self.log("   ⚠️ Re-tentando selecionar Processo...")
                                if await arrow.is_visible(timeout=1000):
                                    await arrow.click(force=True)
                                else:
                                    await proc_select.click(force=True)
                                await asyncio.sleep(0.5)
                                
                                if await inp.is_visible(timeout=1000):
                                    await inp.fill("")
                                    await inp.type("LATAM - Brazil - Logistics", delay=50)
                                else:
                                    await page.keyboard.type("LATAM - Brazil - Logistics", delay=50)
                                    
                                await asyncio.sleep(0.5)
                                await page.keyboard.press("Enter")
                                await asyncio.sleep(0.8)
                                val_text_retry = await proc_select.inner_text()
                                if "Logistics" not in val_text_retry and "LATAM" not in val_text_retry:
                                    raise Exception("O chip do Processo não ficou ativo após a seleção.")

                        self.log("   🟢 [OK] Processo preenchido com sucesso!")
                        await page.wait_for_timeout(1000)

                        # SELEÇÃO DO TIPO DE NOTA*
                        self.log(f"   -> Preenchendo Tipo de Nota: '{note_type}'...")
                        
                        note_container = modal.locator("ng-select").nth(1)
                        if not await note_container.is_visible(timeout=2000):
                            note_container = page.locator("ng-select").nth(1)

                        arrow_note = note_container.locator(".ng-arrow-wrapper, .ng-select-container").first
                        if await arrow_note.is_visible(timeout=2000):
                            await arrow_note.click(force=True)
                        else:
                            await note_container.click(force=True)

                        await asyncio.sleep(0.5)

                        clean_search = note_type.split()[0] if " " in note_type else note_type
                        await page.keyboard.type(clean_search, delay=50)
                        await asyncio.sleep(0.5)

                        opt_note = page.locator(".ng-option").filter(has_text=note_type).first
                        if not await opt_note.is_visible(timeout=1500):
                            opt_note = page.locator(".ng-option").filter(has_text=clean_search).first

                        if await opt_note.is_visible(timeout=1500):
                            await opt_note.click(force=True)
                        else:
                            await page.keyboard.press("Enter")
                        
                        await asyncio.sleep(0.8)
                        note_val_text = await note_container.inner_text()
                        if clean_search not in note_val_text:
                            raise Exception("O chip do Tipo de Nota não ficou ativo.")

                        self.log(f"   🟢 [OK] Tipo de nota preenchido: '{note_type}'")
                        
                        modal_ready = True
                        break # <-- SUCESSO! SAI DO LOOP DE TENTATIVAS DA MODAL!

                except Exception as e_proc_check:
                    self.log(f"   ❌ Falha ao tentar preencher modal: {e_proc_check}")
                    if attempt < max_modal_attempts:
                        self.log("   ⚠️ Fechando modal e tentando de novo...")
                        close_btn = modal.locator("button.close, .modal-header .close, button:has-text('Cancelar'), button:has-text('Close'), .close").first
                        if await close_btn.is_visible(timeout=2000):
                            await close_btn.click(force=True)
                        else:
                            await page.keyboard.press("Escape")
                        await asyncio.sleep(1)
                        continue
                    else:
                        self.log(f"   ⚠️ Limite de {max_modal_attempts} tentativas atingido! Tentando prosseguir para os próximos campos...")
                        break

            # --- 2. Seleção da Prioridade ---
            self.log(f"   -> Selecionando Prioridade: '{priority}'...")
            await self.selecionarPrioridade(page, priority_name=priority.upper())


            # TEXTO DA MENSAGEM (.ql-editor)
            self.log("   -> 4. Preenchendo mensagem no editor (.ql-editor)...")
            try:
                ql_editor = modal.locator('.ql-editor').first
                if not await ql_editor.is_visible(timeout=2000):
                    ql_editor = page.locator('.ql-editor').first
                
                await ql_editor.wait_for(state="visible", timeout=4000)
                await ql_editor.click(force=True)
                
                lines = description.replace('\r\n', '\n').split('\n')
                for idx, line in enumerate(lines):
                    if line:
                        await ql_editor.press_sequentially(line, delay=5)
                    if idx < len(lines) - 1:
                        await page.keyboard.press("Shift+Enter")
                
                self.log("   🟢 [OK] Texto da mensagem digitado perfeitamente no editor!")
            except Exception as e_ed:
                self.log(f"   ⚠️ Falha ao digitar texto no editor: {e_ed}")

            # ANEXAR FOTO / ARQUIVOS (Suporte a anexos sequenciais)
            paths = []
            if isinstance(attachment_path, list):
                paths = [p for p in attachment_path if p and os.path.exists(p)]
            elif isinstance(attachment_path, str) and os.path.exists(attachment_path):
                paths = [attachment_path]

            if paths:
                filenames_str = ", ".join([os.path.basename(p) for p in paths])
                self.log(f"📎 [5/6] Anexando {len(paths)} foto(s) sequencialmente: {filenames_str}...")
                for idx, single_path in enumerate(paths, start=1):
                    try:
                        file_input = modal.locator('input[type="file"]').first
                        if await file_input.count() == 0:
                            file_input = page.locator('input[type="file"]').first

                        if await file_input.count() > 0:
                            await file_input.set_input_files(single_path)
                            await asyncio.sleep(1.5)
                            self.log(f"   🟢 [OK] Foto {idx}/{len(paths)} ({os.path.basename(single_path)}) anexada com sucesso!")
                        else:
                            anexo_btn = modal.get_by_text('Anexos').first
                            if await anexo_btn.is_visible(timeout=2000):
                                async with page.expect_file_chooser() as fc_info:
                                    await anexo_btn.click(force=True)
                                file_chooser = await fc_info.value
                                await file_chooser.set_files(single_path)
                                await asyncio.sleep(1.5)
                                self.log(f"   🟢 [OK] Foto {idx}/{len(paths)} ({os.path.basename(single_path)}) anexada via botão 'Anexos'!")
                    except Exception as e_att:
                        self.log(f"   ⚠️ Falha ao anexar foto {idx} ({os.path.basename(single_path)}): {e_att}")
            else:
                self.log("📎 [5/6] Nenhum anexo de foto pendente para enviar.")

            # --- MODO APROVAÇÃO VISUAL ---
            shots_dir = os.path.join(os.path.dirname(__file__), "static")
            os.makedirs(shots_dir, exist_ok=True)
            fname = f"preview_{delivery_clean}_{int(time.time())}.png"
            shot_file = os.path.join(shots_dir, fname)
            
            # Salva o tamanho atual do viewport para restaurar depois
            old_viewport = page.viewport_size
            try:
                # Aumenta temporariamente a altura do viewport para caber a modal inteira
                await page.set_viewport_size({"width": 1280, "height": 1800})
                await asyncio.sleep(0.3)
                
                # Injeta estilo temporário para forçar a modal a se expandir por inteiro
                await page.evaluate("""() => {
                    const el = document.createElement('style');
                    el.id = 'temp-screenshot-styles';
                    el.innerHTML = `
                        .modal, .modal-dialog, .modal-content, .modal-body {
                            overflow: visible !important;
                            max-height: none !important;
                            height: auto !important;
                        }
                    `;
                    document.head.appendChild(el);
                    
                    // Rola a página para o topo da modal
                    let modal = document.querySelector('.modal-content') || document.querySelector('[role="dialog"]');
                    if (modal) {
                        modal.scrollIntoView({block: 'start'});
                    }
                }""")
                await asyncio.sleep(0.5)
                
                # Tira o print focado apenas na modal (capturando a altura total dela)
                modal_el = page.locator('.modal-content, [role="dialog"]').first
                if await modal_el.is_visible(timeout=1000):
                    await modal_el.screenshot(path=shot_file)
                else:
                    await page.screenshot(path=shot_file, full_page=True)
            except Exception:
                await page.screenshot(path=shot_file, full_page=True)
            finally:
                # Limpa o estilo temporário
                try:
                    await page.evaluate("""() => {
                        const el = document.getElementById('temp-screenshot-styles');
                        if (el) el.remove();
                    }""")
                except Exception:
                    pass
                # Restaura o tamanho do viewport original
                if old_viewport:
                    try:
                        await page.set_viewport_size(old_viewport)
                    except Exception:
                        pass
            
            self.log(f"👀 Aguardando aprovação visual no Painel: /static/{fname}")
            
            approval_event = asyncio.Event()
            self.approval_state = {
                "event": approval_event,
                "action": None,
                "image_url": f"/static/{fname}",
                "delivery": delivery_clean
            }
            
            try:
                await asyncio.wait_for(approval_event.wait(), timeout=300)
                action = self.approval_state.get("action")
            except asyncio.TimeoutError:
                self.log("⚠️ Tempo limite de 5 minutos excedido! Cancelando operação.")
                action = "cancel"
            finally:
                self.approval_state = {"event": None, "action": None, "image_url": None, "delivery": None}

            if action == "approve":
                self.log("💾 [6/6] Usuário aprovou! Clicando no botão 'CRIAR PEDIDO(S)'...")
                save_btn = modal.locator("button:has-text('CRIAR PEDIDO(S)'), button:has-text('CRIAR PEDIDO'), button:has-text('Salvar'), button:has-text('CRIAR NOTA')").first
                if not await save_btn.is_visible(timeout=2000):
                    save_btn = page.locator("button:has-text('CRIAR PEDIDO(S)'), button:has-text('CRIAR PEDIDO')").first

                if await save_btn.is_visible(timeout=3000):
                    await save_btn.click(force=True)
                    await asyncio.sleep(2.5)
                    self.log(f"✅ Ocorrência '{note_type}' criada com sucesso no CHEP!")
                    self.is_creating_occurrence = False
                    return True
                else:
                    self.log("⚠️ Botão 'CRIAR PEDIDO(S)' não encontrado na tela!")
                    self.is_creating_occurrence = False
                    return False
            else:
                self.log("🚫 Ocorrência rejeitada ou cancelada. Fechando a modal.")
                try:
                    # Tenta pegar qualquer botão de fechar VISÍVEL
                    close_btns = page.locator("button.close, .modal-header .close, button:has-text('Cancelar'), button:has-text('Close'), button[aria-label='Close'], span[aria-hidden='true']")
                    closed = False
                    for i in range(await close_btns.count()):
                        if await close_btns.nth(i).is_visible():
                            await close_btns.nth(i).click(force=True)
                            closed = True
                            break
                    
                    if not closed:
                        # Força múltiplos Escapes
                        await page.mouse.click(10, 10) # Clica fora para focar o body
                        await page.keyboard.press("Escape")
                        await asyncio.sleep(0.5)
                        await page.keyboard.press("Escape")
                except Exception:
                    pass
                
                self.is_creating_occurrence = False
                return False

        except Exception as e:
            self.log(f"❌ Erro ao preencher ocorrência: {e}")
            self.is_creating_occurrence = False
            return False

    async def respond_contact_site(
        self,
        delivery_number: str,
        message_text: str,
        profile_name: str = "BR__LH_PURM2",
        attachment_path: str = None
    ) -> str:
        self.is_creating_occurrence = True
        try:
            res = await self.create_contact_chep_response(delivery_number, message_text, profile_name, attachment_path=attachment_path)
            self.is_creating_occurrence = False
            return res
        except Exception as e:
            self.log(f"❌ Erro exato no Service Desk: {e}")
            self.is_creating_occurrence = False
            return "ERROR"

    async def create_contact_chep_response(
        self,
        delivery_number: str,
        reply_message: str,
        profile_name: str = "BR__LH_PURM2",
        test_mode: bool = False,
        attachment_path: str = None
    ) -> str:
        contact_page = await self.get_browser_for_profile(profile_name, site_type="service_desk")

        try:
            self.log(f"\n🌐 [2º Sistema] Abrindo Service Desk (contact.cmaweb.chep.com)...")
            
            try:
                if "contact.cmaweb.chep.com" not in contact_page.url:
                    await contact_page.goto("https://contact.cmaweb.chep.com/workspaces/CHEP/dashboard", wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                self.log(f"⚠️ Erro ao acessar Service Desk (aba morta): {e}. Recriando contexto...")
                clean_profile_id = "PURM3" if "PURM3" in profile_name.upper() else "PURM2"
                if clean_profile_id in self.contexts and self.contexts[clean_profile_id]:
                    try: await self.contexts[clean_profile_id].close()
                    except: pass
                    self.contexts[clean_profile_id] = None
                page_key = f"{clean_profile_id}_service_desk"
                if page_key in self.pages: del self.pages[page_key]
                contact_page = await self.get_browser_for_profile(profile_name, site_type="service_desk")
                await contact_page.goto("https://contact.cmaweb.chep.com/workspaces/CHEP/dashboard", wait_until="domcontentloaded", timeout=15000)
            
            await asyncio.sleep(2)

            is_logged = await self.ensure_user_is_logged_in(contact_page, profile_name)
            if not is_logged:
                return "ERROR"

            opened_btn = contact_page.locator("a[href*='requests'], a:has-text('Opened'), div:has-text('Note(s) Opened'), div:has-text('Opened'), button:has-text('Opened')").first
            if await opened_btn.is_visible(timeout=3000):
                await opened_btn.click()
                await asyncio.sleep(1.5)

            search_box = contact_page.locator("input[placeholder*='Search by delivery'], input[placeholder*='delivery number'], input.form-control").first
            if not await search_box.is_visible(timeout=3000):
                await contact_page.goto("https://contact.cmaweb.chep.com/workspaces/CHEP/requests?page=0&step=10", wait_until="domcontentloaded")
                await asyncio.sleep(2)
                search_box = contact_page.locator("input[placeholder*='Search by delivery'], input[placeholder*='delivery number'], input.form-control").first

            if await search_box.is_visible(timeout=4000):
                await search_box.click()
                await search_box.fill(delivery_number)
                await asyncio.sleep(0.5)
                search_btn = contact_page.locator("button:has-text('Search'), button:has-text('Pesquisar')").first
                if await search_btn.is_visible(timeout=2000):
                    await search_btn.click()
                else:
                    await search_box.press("Enter")
                await asyncio.sleep(2.5)

            table_rows = contact_page.locator("table tbody tr")
            try:
                await table_rows.first.wait_for(state="visible", timeout=15000)
            except Exception as wait_e:
                self.log(f"   ⚠️ Timeout aguardando as linhas da tabela. A pesquisa por {delivery_number} pode não ter retornado resultados ou o site está muito lento.")
                await self.save_debug_screenshot(contact_page, f"timeout_tabela_{delivery_number}", f"Print falha tabela #{delivery_number}")
                return "ERROR_NOT_FOUND"
            row_text = await table_rows.first.inner_text()
            row_lower = row_text.lower()
            if "pending carrier reply" in row_lower or ("carrier reply" in row_lower and "internal" not in row_lower):
                self.log("🚨 [DESLOCAMENTO VAZIO] Status na tabela é 'Pending carrier reply' (Roxo)! Tirando print e avisando...")
                await self.save_debug_screenshot(contact_page, f"roxo_{delivery_number}", f"Print Status Roxo #{delivery_number}")
                return "PENDING_CARRIER_REPLY"

            # Se estiver Amarelo (Pending internal reply), clica na última nota (primeira linha da lista organizada por data mais recente)
            self.log(f"🟡 Status Amarelo (Pending internal reply)! Clicando na última nota da delivery #{delivery_number}...")
            await table_rows.first.click()
            await asyncio.sleep(2)

            # Localiza especificamente a caixa 'Add a message...' selecionando o primeiro que estiver visível
            all_editors = contact_page.locator(".ql-editor, [contenteditable='true']")
            editor = all_editors.last
            try:
                count = await all_editors.count()
                for i in reversed(range(count)):
                    if await all_editors.nth(i).is_visible(timeout=1000):
                        editor = all_editors.nth(i)
                        break
                await editor.wait_for(state="visible", timeout=5000)
                await editor.click(force=True)
            except Exception as e:
                self.log(f"   ⚠️ Aviso ao localizar editor: {e}")
                editor = contact_page.locator("[contenteditable='true']").last
                await editor.click(force=True)
            
            await asyncio.sleep(0.5)

            await asyncio.sleep(0.5)
            await editor.click()
            lines = reply_message.replace('\r\n', '\n').split('\n')
            for idx, line in enumerate(lines):
                if line:
                    await editor.press_sequentially(line, delay=5)
                if idx < len(lines) - 1:
                    await contact_page.keyboard.press("Shift+Enter")
            await asyncio.sleep(0.5)
            await contact_page.keyboard.press("Space")
            await contact_page.keyboard.press("Backspace")
            await asyncio.sleep(1)

            # ANEXAR FOTO / ARQUIVOS NO SERVICE DESK (2º SITE - SEQUENCIAL)
            paths = []
            if isinstance(attachment_path, list):
                paths = [p for p in attachment_path if p and os.path.exists(p)]
            elif isinstance(attachment_path, str) and os.path.exists(attachment_path):
                paths = [attachment_path]

            if paths:
                filenames_str = ", ".join([os.path.basename(p) for p in paths])
                self.log(f"📎 [Service Desk] Anexando {len(paths)} foto(s) sequencialmente: {filenames_str}...")
                for idx, single_path in enumerate(paths, start=1):
                    try:
                        file_input = contact_page.locator("input[type='file']").first
                        if await file_input.count() > 0:
                            await file_input.set_input_files(single_path)
                            await asyncio.sleep(2)
                            self.log(f"   🟢 [OK] Foto {idx}/{len(paths)} ({os.path.basename(single_path)}) anexada no Service Desk com sucesso!")
                        else:
                            select_file_btn = contact_page.locator("a:has-text('or select a file'), label:has-text('or select a file'), :has-text('or select a file')").last
                            if await select_file_btn.is_visible(timeout=3000):
                                async with contact_page.expect_file_chooser() as fc_info:
                                    await select_file_btn.click(force=True)
                                file_chooser = await fc_info.value
                                await file_chooser.set_files(single_path)
                                await asyncio.sleep(2)
                                self.log(f"   🟢 [OK] Foto {idx}/{len(paths)} ({os.path.basename(single_path)}) anexada via botão no Service Desk!")
                    except Exception as e_att:
                        self.log(f"   ⚠️ Falha ao anexar foto {idx} no Service Desk: {e_att}")

            send_btn = contact_page.locator("button:has(.fa-paper-plane), button:has-text('Send'), button.btn-primary:has(svg)").first
            if await send_btn.is_visible(timeout=3000):
                # --- MODO APROVAÇÃO VISUAL ANTES DE ENVIAR NO SERVICE DESK ---
                shots_dir = os.path.join(os.path.dirname(__file__), "static")
                os.makedirs(shots_dir, exist_ok=True)
                fname = f"preview_service_desk_{delivery_number}_{int(time.time())}.png"
                shot_file = os.path.join(shots_dir, fname)
                await contact_page.screenshot(path=shot_file)
                
                self.log(f"⏳ [Service Desk] Aguardando sua aprovação visual no Painel antes de clicar em Enviar: /static/{fname}")
                
                approval_event = asyncio.Event()
                self.approval_state = {
                    "event": approval_event,
                    "action": None,
                    "image_url": f"/static/{fname}",
                    "delivery": delivery_number
                }

                try:
                    await asyncio.wait_for(approval_event.wait(), timeout=300)
                except asyncio.TimeoutError:
                    self.log("⏳ Tempo limite de aprovação esgotado (300s). Operação cancelada.")
                    self.approval_state = None
                    return "CANCELLED"

                user_action = self.approval_state.get("action")
                self.approval_state = None

                if user_action != "approve":
                    self.log("❌ Ocorrência no Service Desk CANCELADA por você no Painel!")
                    return "CANCELLED"

                self.log("✅ [Aprovação Concedida] Clicando em Enviar no Service Desk...")
                await send_btn.click()
                await asyncio.sleep(2)
                self.log("✅ Resposta enviada com sucesso no Service Desk!")
                await self.save_debug_screenshot(contact_page, f"resposta_enviada_{delivery_number}", f"Print Resposta Enviada #{delivery_number}")
                return "SUCCESS"
            return "SUCCESS"

        except Exception as e:
            self.log(f"❌ Erro no 2º site: {e}")
            return "ERROR"

    async def check_pending_carrier_replies(self, daily_deliveries: List[str], profile_name: str = "BR__LH_PURM2") -> List[str]:
        contact_page = await self.get_browser_for_profile(profile_name, site_type="service_desk_monitor")

        answered_deliveries = []
        try:
            self.log(f"🔍 [Monitor] Verificando {len(daily_deliveries)} deliveries no Service Desk ({profile_name})...")
            
            target_url = "https://contact.cmaweb.chep.com/workspaces/CHEP/requests?page=0&step=10"
            try:
                if "contact.cmaweb.chep.com" not in contact_page.url:
                    await contact_page.goto(target_url, wait_until="domcontentloaded", timeout=8000)
            except Exception as e:
                self.log(f"⚠️ Erro ao acessar Service Desk (aba morta): {e}. Recriando contexto...")
                clean_profile_id = "PURM3" if "PURM3" in profile_name.upper() else "PURM2"
                if clean_profile_id in self.contexts and self.contexts[clean_profile_id]:
                    try: await self.contexts[clean_profile_id].close()
                    except: pass
                    self.contexts[clean_profile_id] = None
                page_key = f"{clean_profile_id}_service_desk"
                if page_key in self.pages: del self.pages[page_key]
                contact_page = await self.get_browser_for_profile(profile_name, site_type="service_desk")
                await contact_page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
                
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

            # Traz o Chrome para a frente (faz piscar laranja na barra de tarefas se estiver em segundo plano)
            try:
                await contact_page.bring_to_front()
            except:
                pass

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
                last_msg_time = None
                overdue_notes = []
                for i in range(count):
                    row_text = await table_rows.nth(i).inner_text()
                    row_lower = row_text.lower()
                    
                    if "no results" in row_lower or "0 results" in row_lower:
                        continue
                    
                    self.log(f"📄 [Debug] Row content: {row_text.strip()}")

                    if "pending carrier reply" in row_lower or ("carrier reply" in row_lower and "internal" not in row_lower):
                        has_purple_reply = True

                    # Tenta extrair a data/hora do "Last message sent"
                    try:
                        cells = table_rows.nth(i).locator("td")
                        cell_count = await cells.count()
                        for c_idx in range(cell_count):
                            c_text = (await cells.nth(c_idx).inner_text()).strip()
                            if "/" in c_text and ":" in c_text and len(c_text) >= 14:
                                from datetime import datetime
                                parts = c_text.split()
                                if len(parts) >= 2:
                                    dt_str = f"{parts[0]} {parts[1]}"
                                    last_sent_dt = datetime.strptime(dt_str, "%d/%m/%Y %H:%M")
                                    last_msg_time = dt_str
                                    diff_minutes = (datetime.now() - last_sent_dt).total_seconds() / 60.0
                                    if diff_minutes >= 70:
                                        overdue_notes.append((c_text, int(diff_minutes)))
                                    break
                    except Exception:
                        pass

                if has_purple_reply:
                    self.log(f"🟣 [RESPONDIDA PELA CHEP] Delivery #{deliv_clean} possui status ROXO (Pending carrier reply)!")
                    
                    import time
                    import os
                    print_name = f"print_roxo_{deliv_clean}_{int(time.time())}.png"
                    print_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots", print_name)
                    os.makedirs(os.path.dirname(print_path), exist_ok=True)
                    try:
                        await contact_page.screenshot(path=print_path)
                        self.log(f"📸 Print da Resposta: <a href='/screenshots/{print_name}' target='_blank' style='color: #c084fc; text-decoration: underline; font-weight: bold;'>[Visualizar Resposta ROXA da CHEP]</a>")
                    except Exception:
                        pass
                        
                    answered_deliveries.append((deliv_clean, True, False, last_msg_time))
                elif overdue_notes:
                    last_time_str, mins = overdue_notes[0]
                    self.log(f"⏰ [ATENÇÃO > 1H] Delivery #{deliv_clean}: Última mensagem enviada há {mins} min ({last_time_str})! Já passou de 1h10, hora de atualizar nova ocorrência!")
                    answered_deliveries.append((deliv_clean, False, True, last_msg_time))
                else:
                    self.log(f"🟡 Delivery #{deliv_clean}: Status na tabela é Amarelo (Pending internal reply).")
                    answered_deliveries.append((deliv_clean, False, False, last_msg_time))

            if not answered_deliveries:
                self.log("🟢 Nenhuma nova resposta roxa ou pendência > 1h encontrada.")
            
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

