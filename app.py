import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time
import gspread
from google.oauth2.service_account import Credentials

# -------------------- CONFIGURAÇÃO DA PÁGINA --------------------
st.set_page_config(
    page_title="Dashboard Financeiro",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ==================== SISTEMA DE CACHE INTELIGENTE ====================
class SheetsCache:
    """Gerenciador de cache inteligente para Google Sheets."""
    
    def __init__(self, default_ttl=30):
        self.cache = {}
        self.default_ttl = default_ttl
        self.stats = {"hits": 0, "misses": 0}
    
    def get(self, key, fetch_function, ttl=None):
        """Busca do cache com fallback para função de fetch."""
        current_time = time.time()
        ttl = ttl or self.default_ttl
        
        if key in self.cache:
            entry = self.cache[key]
            if current_time - entry["timestamp"] < ttl:
                self.stats["hits"] += 1
                return entry["data"]
        
        # Cache miss - busca dados novos
        self.stats["misses"] += 1
        data = fetch_function()
        
        self.cache[key] = {
            "data": data,
            "timestamp": current_time
        }
        
        # Limpa caches antigos a cada 100 misses
        if self.stats["misses"] % 100 == 0:
            self._clean_old_entries()
        
        return data
    
    def invalidate(self, key_pattern=None):
        """Invalida cache parcial ou total."""
        if key_pattern is None:
            self.cache.clear()
            self.stats = {"hits": 0, "misses": 0}
        else:
            keys_to_delete = [k for k in self.cache if key_pattern in k]
            for k in keys_to_delete:
                del self.cache[k]
    
    def _clean_old_entries(self, max_age=300):  # 5 minutos
        """Remove entradas antigas do cache."""
        current_time = time.time()
        keys_to_delete = [
            k for k, v in self.cache.items()
            if current_time - v["timestamp"] > max_age
        ]
        for k in keys_to_delete:
            del self.cache[k]
    
    def get_stats(self):
        """Retorna estatísticas do cache."""
        total = self.stats["hits"] + self.stats["misses"]
        hit_ratio = self.stats["hits"] / total if total > 0 else 0
        return {
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "hit_ratio": hit_ratio,
            "cache_size": len(self.cache)
        }

# Inicializa o cache global
_sheets_cache = SheetsCache(default_ttl=30)

# -------------------- GOOGLE SHEETS INTEGRAÇÃO --------------------
def get_gspread_client():
    """Retorna cliente autenticado do gspread usando service account."""
    creds_dict = st.secrets["gcp_service_account"]
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    return gspread.authorize(creds)

# Cache para a planilha principal (TTL maior - 5 minutos)
def get_spreadsheet():
    """Abre a planilha principal com cache de 5 minutos."""
    def _fetch_spreadsheet():
        client = get_gspread_client()
        SPREADSHEET_ID = "1b7QQ2n59e_GCijiWmTrKBeq7-FnXgVttx9l96uuIs0I"
        return client.open_by_key(SPREADSHEET_ID)
    
    return _sheets_cache.get("spreadsheet", _fetch_spreadsheet, ttl=300)

def get_usuarios_worksheet():
    """Retorna a worksheet de usuários com verificação."""
    try:
        spreadsheet = get_spreadsheet()
        all_worksheets = [ws.title for ws in spreadsheet.worksheets()]
        
        if "usuarios" not in all_worksheets:
            st.error(f"❌ Aba 'usuarios' não encontrada! Abas disponíveis: {all_worksheets}")
            st.stop()
        
        return spreadsheet.worksheet("usuarios")
    except Exception as e:
        st.error(f"Erro ao acessar aba 'usuarios': {str(e)}")
        st.stop()

def get_gastos_worksheet():
    """Retorna a worksheet de gastos com verificação."""
    try:
        spreadsheet = get_spreadsheet()
        all_worksheets = [ws.title for ws in spreadsheet.worksheets()]
        
        if "gastos" not in all_worksheets:
            st.error(f"❌ Aba 'gastos' não encontrada! Abas disponíveis: {all_worksheets}")
            st.stop()
        
        return spreadsheet.worksheet("gastos")
    except Exception as e:
        st.error(f"Erro ao acessar aba 'gastos': {str(e)}")
        st.stop()

def normalizar_cabecalhos(linha):
    """Converte lista de cabeçalhos para minúsculas e sem espaços."""
    return [str(celula).strip().lower() for celula in linha]

def mapear_indices(worksheet, colunas_esperadas):
    """
    Retorna um dicionário {nome_coluna: indice} baseado nos cabeçalhos da worksheet.
    Se alguma coluna obrigatória não for encontrada, exibe erro e interrompe.
    """
    cabecalhos = worksheet.row_values(1)
    cab_norm = normalizar_cabecalhos(cabecalhos)
    indices = {}
    for col in colunas_esperadas:
        try:
            indices[col] = cab_norm.index(col)
        except ValueError:
            st.error(f"❌ Coluna obrigatória '{col}' não encontrada na planilha. "
                     f"Cabeçalhos encontrados: {cabecalhos}")
            st.stop()
    return indices

def check_user(email):
    """Verifica se o email existe na planilha de usuários (case‑insensitive)."""
    try:
        ws = get_usuarios_worksheet()
        all_rows = ws.get_all_values()
        if len(all_rows) < 2:
            return None

        expected = ["email", "renda_mensal"]
        indices = mapear_indices(ws, expected)

        email_clean = email.lower().strip()
        for i, row in enumerate(all_rows[1:], start=2):
            if len(row) <= indices["email"]:
                continue
            if row[indices["email"]].lower().strip() == email_clean:
                renda_valor = row[indices["renda_mensal"]] if len(row) > indices["renda_mensal"] else "0"
                renda_valor = renda_valor.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".").strip()
                try:
                    renda_float = float(renda_valor) if renda_valor else 0.0
                except ValueError:
                    renda_float = 0.0
                return {
                    "row": i,
                    "data": {"email": row[indices["email"]], "renda_mensal": renda_float}
                }
        return None
    except Exception as e:
        st.error(f"Erro ao verificar usuário: {str(e)}")
        return None

def load_user_data(email):
    """Carrega renda e gastos do usuário com mapeamento flexível de colunas."""
    user_info = check_user(email)
    if not user_info:
        return 0.0, []

    renda = user_info["data"]["renda_mensal"]

    try:
        ws_gastos = get_gastos_worksheet()
        expected = ["email", "id", "descricao", "categoria", "valor", "data", "forma_pagamento", "timestamp"]
        indices = mapear_indices(ws_gastos, expected)

        all_rows = ws_gastos.get_all_values()
        if len(all_rows) < 2:
            return renda, []

        gastos_usuario = []
        email_clean = email.lower().strip()

        for row in all_rows[1:]:
            if len(row) <= max(indices.values()):
                continue  # linha incompleta

            if row[indices["email"]].lower().strip() != email_clean:
                continue

            valor_raw = row[indices["valor"]]
            valor_raw = valor_raw.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".").strip()
            try:
                valor_float = float(valor_raw) if valor_raw else 0.0
            except ValueError:
                valor_float = 0.0

            gasto = {
                "id": row[indices["id"]],
                "descricao": row[indices["descricao"]],
                "categoria": row[indices["categoria"]],
                "valor": valor_float,
                "data": row[indices["data"]],
                "forma_pagamento": row[indices["forma_pagamento"]],
                "timestamp": row[indices["timestamp"]]
            }
            gastos_usuario.append(gasto)

        return renda, gastos_usuario
    except Exception as e:
        st.error(f"Erro ao carregar gastos: {str(e)}")
        return renda, []

# Versões com cache das funções principais
def get_user_data_cached(email):
    """Versão otimizada de load_user_data com cache."""
    cache_key = f"user_data_{email}"
    
    def _fetch():
        return load_user_data(email)
    
    return _sheets_cache.get(cache_key, _fetch, ttl=30)

def save_renda_cached(email, nova_renda):
    """Versão otimizada que invalida cache após salvar."""
    user_info = check_user(email)
    if user_info:
        ws = get_usuarios_worksheet()
        indices = mapear_indices(ws, ["email", "renda_mensal"])
        ws.update_cell(user_info["row"], indices["renda_mensal"] + 1, float(nova_renda))
        st.session_state.dados["renda_mensal"] = nova_renda
        
        # Invalida caches relacionados
        _sheets_cache.invalidate(f"user_data_{email}")
        _sheets_cache.invalidate("worksheet_usuarios")
        return True
    st.error("Usuário não encontrado.")
    return False

def add_gasto_cached(email, gasto):
    """Versão otimizada que invalida cache após adicionar."""
    try:
        ws_gastos = get_gastos_worksheet()
        expected = ["email", "id", "descricao", "categoria", "valor", "data", "forma_pagamento", "timestamp"]
        indices = mapear_indices(ws_gastos, expected)

        num_cols = len(ws_gastos.row_values(1))
        nova_linha = [""] * num_cols
        gasto_id = f"{datetime.now().timestamp()}_{email}"
        nova_linha[indices["email"]] = email
        nova_linha[indices["id"]] = gasto_id
        nova_linha[indices["descricao"]] = gasto["descricao"]
        nova_linha[indices["categoria"]] = gasto["categoria"]
        nova_linha[indices["valor"]] = float(gasto["valor"])
        nova_linha[indices["data"]] = gasto["data"]
        nova_linha[indices["forma_pagamento"]] = gasto["forma_pagamento"]
        nova_linha[indices["timestamp"]] = gasto["timestamp"]

        ws_gastos.append_row(nova_linha)
        gasto['id'] = gasto_id
        st.session_state.dados['gastos'].append(gasto)
        
        # Invalida caches relacionados
        _sheets_cache.invalidate(f"user_data_{email}")
        _sheets_cache.invalidate("worksheet_gastos")
        return gasto_id
    except Exception as e:
        st.error(f"Erro ao adicionar gasto: {str(e)}")
        return None

def delete_all_user_data_cached(email):
    """Versão otimizada que invalida cache após deletar."""
    try:
        # Deletar gastos
        ws_gastos = get_gastos_worksheet()
        expected = ["email", "id", "descricao", "categoria", "valor", "data", "forma_pagamento", "timestamp"]
        indices = mapear_indices(ws_gastos, expected)

        all_rows = ws_gastos.get_all_values()
        if len(all_rows) > 1:
            linhas_para_deletar = []
            email_clean = email.lower().strip()
            for i, row in enumerate(all_rows[1:], start=2):
                if len(row) > indices["email"] and row[indices["email"]].lower().strip() == email_clean:
                    linhas_para_deletar.append(i)
            for row_num in sorted(linhas_para_deletar, reverse=True):
                ws_gastos.delete_rows(row_num)

        # Zerar renda
        user_info = check_user(email)
        if user_info:
            ws_usuarios = get_usuarios_worksheet()
            indices_user = mapear_indices(ws_usuarios, ["email", "renda_mensal"])
            ws_usuarios.update_cell(user_info["row"], indices_user["renda_mensal"] + 1, 0)
            st.session_state.dados['renda_mensal'] = 0
            st.session_state.dados['gastos'] = []
        
        # Invalida caches relacionados
        _sheets_cache.invalidate(f"user_data_{email}")
        _sheets_cache.invalidate("worksheet_usuarios")
        _sheets_cache.invalidate("worksheet_gastos")
        return True
    except Exception as e:
        st.error(f"Erro ao limpar dados: {str(e)}")
        return False

# -------------------- INICIALIZAÇÃO DO SESSION STATE --------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "email" not in st.session_state:
    st.session_state.email = None
if "dados" not in st.session_state:
    st.session_state.dados = {"renda_mensal": 0, "gastos": []}
if "confirmar_limpeza" not in st.session_state:
    st.session_state.confirmar_limpeza = False
if "ultima_acao" not in st.session_state:
    st.session_state.ultima_acao = None
if "login_error" not in st.session_state:
    st.session_state.login_error = None
if "show_cache_stats" not in st.session_state:
    st.session_state.show_cache_stats = False

CHECKOUT_URL = "https://pay.cakto.com.br/xxienb8_809928"

# -------------------- VERIFICAÇÃO INICIAL --------------------
try:
    sheet = get_spreadsheet()
    worksheets = sheet.worksheets()
    ws_titles = [ws.title for ws in worksheets]
    if "usuarios" not in ws_titles:
        st.error("❌ Aba 'usuarios' não encontrada! Verifique o nome da aba.")
        st.stop()
    if "gastos" not in ws_titles:
        st.error("❌ Aba 'gastos' não encontrada! Verifique o nome da aba.")
        st.stop()
except Exception as e:
    st.error(f"❌ Erro de conexão com a planilha: {str(e)}")
    st.stop()

# -------------------- TELA DE LOGIN --------------------
if not st.session_state.authenticated:
    col_center = st.columns([1, 3, 1])[1]
    with col_center:
        st.markdown("""
        <div style="background: linear-gradient(145deg, #1e293b, #0f172a); padding: 3rem; border-radius: 30px; border: 1px solid #8b5cf6; margin-top: 3rem;">
            <h2 style="color: white; text-align: center; margin-bottom: 2rem;">🔐 Acesso Restrito</h2>
        """, unsafe_allow_html=True)

        email = st.text_input("Seu e-mail cadastrado", placeholder="email@exemplo.com")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Entrar", use_container_width=True, type="primary"):
                if email:
                    with st.spinner("Verificando credenciais..."):
                        user = check_user(email)
                        if user:
                            st.session_state.authenticated = True
                            st.session_state.email = email
                            st.session_state.login_error = None
                            st.rerun()
                        else:
                            st.session_state.login_error = email
                            st.rerun()
                else:
                    st.warning("⚠️ Digite seu e-mail.")

        with col2:
            st.markdown(f"""
            <a href="{CHECKOUT_URL}" target="_blank" style="text-decoration: none;">
                <div style="background: linear-gradient(135deg, #10b981, #059669); color: white; padding: 0.6rem; border-radius: 12px; text-align: center; font-weight: 600; font-size: 0.9rem; box-shadow: 0 4px 15px rgba(16, 185, 129, 0.4);">
                    💳 ASSINAR AGORA
                </div>
            </a>
            """, unsafe_allow_html=True)

        if st.session_state.login_error:
            st.markdown(f"""
            <div style="margin-top: 2rem; padding: 1.5rem; background: rgba(239, 68, 68, 0.1); border-radius: 15px; border: 1px solid rgba(239, 68, 68, 0.3); text-align: center;">
                <p style="color: #f87171; font-size: 1.1rem; font-weight: 600; margin: 0;">❌ E-mail não encontrado</p>
                <p style="color: #94a3b8; margin: 0.5rem 0; font-size: 0.9rem;">O e-mail <strong>{st.session_state.login_error}</strong> não possui acesso ativo.</p>
                <div style="margin: 1rem 0; padding: 1rem; background: rgba(16, 185, 129, 0.1); border-radius: 12px; border: 1px solid rgba(16, 185, 129, 0.3);">
                    <p style="color: #10b981; font-weight: 600; margin: 0 0 0.5rem 0;">🚀 Desbloqueie seu acesso agora!</p>
                    <p style="color: #94a3b8; font-size: 0.85rem; margin: 0;">Assine por apenas <span style="color: #10b981; font-weight: 700;">R$ 10,99/mês</span> e tenha controle total das suas finanças.</p>
                </div>
                <a href="{CHECKOUT_URL}" target="_blank" style="text-decoration: none;">
                    <div style="background: linear-gradient(135deg, #8b5cf6, #06b6d4); color: white; padding: 0.75rem 1.5rem; border-radius: 12px; font-weight: 600; display: inline-block; box-shadow: 0 4px 15px rgba(139, 92, 246, 0.4);">
                        👉 Quero meu acesso agora
                    </div>
                </a>
                <p style="color: #64748b; margin: 1rem 0 0 0; font-size: 0.75rem;">* Após a confirmação do pagamento, seu e-mail será liberado em até 24h.</p>
            </div>
            """, unsafe_allow_html=True)

            if st.button("🔄 Tentar outro e-mail", use_container_width=True):
                st.session_state.login_error = None
                st.rerun()
        else:
            st.markdown("""
            <div style="margin-top: 2rem; padding: 1rem; background: rgba(139, 92, 246, 0.1); border-radius: 12px; border: 1px solid rgba(139, 92, 246, 0.3); text-align: center;">
                <p style="color: #94a3b8; margin: 0; font-size: 0.9rem;">
                    ⚡ <strong>Não tem acesso?</strong> Assine por apenas <span style="color: #10b981; font-weight: 700;">R$ 10,99/mês</span>
                </p>
                <p style="color: #64748b; margin: 0.5rem 0 0 0; font-size: 0.8rem;">
                    Após a assinatura, seu e-mail será liberado em até 24h.
                </p>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

# -------------------- APÓS LOGIN: CARREGA DADOS COM CACHE --------------------
with st.spinner("Carregando seus dados..."):
    renda, gastos = get_user_data_cached(st.session_state.email)
    st.session_state.dados["renda_mensal"] = renda
    st.session_state.dados["gastos"] = gastos

# ==================== CSS (igual ao original) ====================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    * { font-family: 'Inter', sans-serif; }
    .stApp { background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%); color: #e2e8f0; }
    .metric-card { background: linear-gradient(145deg, #1e293b 0%, #334155 100%); border-radius: 20px; padding: 1.5rem; border: 1px solid rgba(148, 163, 184, 0.1); box-shadow: 0 10px 40px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.05); backdrop-filter: blur(10px); transition: all 0.3s ease; position: relative; overflow: hidden; }
    .metric-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; background: linear-gradient(90deg, #8b5cf6, #06b6d4, #10b981); }
    .metric-card:hover { transform: translateY(-5px); box-shadow: 0 20px 60px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.1); }
    .metric-value { font-size: 2rem; font-weight: 700; background: linear-gradient(135deg, #e2e8f0 0%, #94a3b8 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin: 0; }
    .metric-value.positive { background: linear-gradient(135deg, #10b981 0%, #34d399 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .metric-value.negative { background: linear-gradient(135deg, #ef4444 0%, #f87171 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .metric-label { color: #94a3b8; font-size: 0.875rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }
    .metric-delta { font-size: 0.875rem; font-weight: 600; margin-top: 0.5rem; color: #64748b; }
    .dashboard-header { background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #312e81 100%); color: white; padding: 2rem 1rem; border-radius: 0 0 30px 30px; margin: -1rem -1rem 2rem -1rem; box-shadow: 0 10px 40px rgba(139, 92, 246, 0.2); border-bottom: 1px solid rgba(139, 92, 246, 0.2); }
    .dashboard-title { font-size: 2rem; font-weight: 700; margin: 0; text-align: center; background: linear-gradient(135deg, #e2e8f0 0%, #8b5cf6 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    .dashboard-subtitle { font-size: 1rem; color: #94a3b8; text-align: center; margin-top: 0.5rem; }
    .chart-container { background: linear-gradient(145deg, #1e293b 0%, #0f172a 100%); border-radius: 20px; padding: 1.5rem; border: 1px solid rgba(148, 163, 184, 0.1); box-shadow: 0 4px 20px rgba(0,0,0,0.4); margin-bottom: 1rem; }
    .form-container { background: linear-gradient(145deg, #1e293b 0%, #334155 100%); border-radius: 20px; padding: 2rem; border: 1px solid rgba(139, 92, 246, 0.2); box-shadow: 0 10px 40px rgba(0,0,0,0.4); }
    .stTextInput>div>div>input, .stNumberInput>div>div>input { background: #0f172a !important; color: #e2e8f0 !important; border: 2px solid #334155 !important; border-radius: 12px !important; padding: 0.75rem !important; }
    .stTextInput>div>div>input:focus, .stNumberInput>div>div>input:focus { border-color: #8b5cf6 !important; box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.1) !important; }
    .stSelectbox>div>div>div { background: #0f172a !important; color: #e2e8f0 !important; border: 2px solid #334155 !important; border-radius: 12px !important; }
    .stDateInput>div>div>input { background: #0f172a !important; color: #e2e8f0 !important; border: 2px solid #334155 !important; border-radius: 12px !important; }
    .stButton>button { width: 100%; border-radius: 12px; background: linear-gradient(135deg, #8b5cf6 0%, #06b6d4 100%); color: white; border: none; padding: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; transition: all 0.3s ease; box-shadow: 0 4px 15px rgba(139, 92, 246, 0.4); }
    .stButton>button:hover { transform: translateY(-2px); box-shadow: 0 8px 25px rgba(139, 92, 246, 0.6); }
    .stButton>button:active { transform: translateY(0); }
    .btn-danger { background: linear-gradient(135deg, #ef4444 0%, #f97316 100%) !important; box-shadow: 0 4px 15px rgba(239, 68, 68, 0.4) !important; }
    .dataframe { background: linear-gradient(145deg, #1e293b 0%, #0f172a 100%) !important; border-radius: 15px !important; border: 1px solid rgba(148, 163, 184, 0.1) !important; color: #e2e8f0 !important; }
    .dataframe th { background: linear-gradient(90deg, #1e293b, #334155) !important; color: #e2e8f0 !important; padding: 15px !important; border-bottom: 2px solid #8b5cf6 !important; font-weight: 600 !important; text-transform: uppercase !important; font-size: 0.875rem !important; }
    .dataframe td { background: transparent !important; color: #e2e8f0 !important; padding: 12px !important; border-bottom: 1px solid #334155 !important; }
    .dataframe tr:hover td { background: rgba(139, 92, 246, 0.1) !important; }
    .category-badge { display: inline-block; padding: 0.25rem 0.75rem; border-radius: 20px; font-size: 0.75rem; font-weight: 600; text-transform: uppercase; box-shadow: 0 2px 10px rgba(0,0,0,0.3); }
    .cat-alimentacao { background: rgba(245, 158, 11, 0.2); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.3); }
    .cat-transporte { background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); }
    .cat-lazer { background: rgba(236, 72, 153, 0.2); color: #f472b6; border: 1px solid rgba(236, 72, 153, 0.3); }
    .cat-moradia { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }
    .cat-saude { background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.3); }
    .cat-educacao { background: rgba(139, 92, 246, 0.2); color: #a78bfa; border: 1px solid rgba(139, 92, 246, 0.3); }
    .cat-vestuario { background: rgba(14, 165, 233, 0.2); color: #38bdf8; border: 1px solid rgba(14, 165, 233, 0.3); }
    .cat-tecnologia { background: rgba(99, 102, 241, 0.2); color: #818cf8; border: 1px solid rgba(99, 102, 241, 0.3); }
    .cat-outros { background: rgba(100, 116, 139, 0.2); color: #94a3b8; border: 1px solid rgba(100, 116, 139, 0.3); }
    .progress-container { background: #334155; border-radius: 10px; height: 10px; overflow: hidden; margin-top: 0.5rem; box-shadow: inset 0 2px 4px rgba(0,0,0,0.3); }
    .progress-bar { height: 100%; border-radius: 10px; background: linear-gradient(90deg, #8b5cf6 0%, #06b6d4 100%); transition: width 0.5s ease; box-shadow: 0 0 10px rgba(139, 92, 246, 0.5); }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: translateY(0); } }
    @keyframes glow { 0%, 100% { box-shadow: 0 0 5px rgba(139, 92, 246, 0.5); } 50% { box-shadow: 0 0 20px rgba(139, 92, 246, 0.8); } }
    @keyframes slideIn { from { transform: translateX(100%); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
    .animate-in { animation: fadeIn 0.6s ease-out; }
    .glow-effect { animation: glow 2s infinite; }
    .toast-success { background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important; color: white !important; border: none !important; border-radius: 12px !important; box-shadow: 0 10px 30px rgba(16, 185, 129, 0.4) !important; }
    .toast-error { background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%) !important; color: white !important; border: none !important; border-radius: 12px !important; box-shadow: 0 10px 30px rgba(239, 68, 68, 0.4) !important; }
    .summary-card { background: linear-gradient(145deg, #1e293b 0%, #0f172a 100%); border-radius: 15px; padding: 1rem; border-left: 4px solid; margin-bottom: 1rem; }
    .summary-card.renda { border-left-color: #10b981; }
    .summary-card.gastos { border-left-color: #ef4444; }
    .summary-card.saldo { border-left-color: #06b6d4; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; background: rgba(30, 41, 59, 0.5); padding: 0.5rem; border-radius: 15px; margin-bottom: 1rem; }
    .stTabs [data-baseweb="tab"] { background: transparent; color: #94a3b8; border-radius: 10px; padding: 0.75rem 1.5rem; font-weight: 500; }
    .stTabs [aria-selected="true"] { background: linear-gradient(135deg, #8b5cf6 0%, #06b6d4 100%) !important; color: white !important; }
    @media (max-width: 768px) { .metric-value { font-size: 1.5rem; } .dashboard-title { font-size: 1.5rem; } .chart-container { padding: 1rem; } }
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-track { background: #0f172a; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 5px; }
    ::-webkit-scrollbar-thumb:hover { background: #475569; }
    .status-indicator { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.5rem 1rem; border-radius: 20px; font-size: 0.875rem; font-weight: 500; }
    .status-success { background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); }
</style>
""", unsafe_allow_html=True)

# ==================== FUNÇÕES AUXILIARES ====================
def notificar_sucesso(mensagem, detalhe=None):
    if detalhe:
        st.toast(f"✓ {mensagem}", icon="✅")
        time.sleep(0.1)
        st.toast(f"💡 {detalhe}", icon="ℹ️")
    else:
        st.toast(f"✓ {mensagem}", icon="✅")

def notificar_erro(mensagem, solucao=None):
    if solucao:
        st.toast(f"✗ {mensagem}", icon="❌")
        time.sleep(0.1)
        st.toast(f"💡 {solucao}", icon="💡")
    else:
        st.toast(f"✗ {mensagem}", icon="❌")

def notificar_info(mensagem):
    st.toast(f"ℹ️ {mensagem}", icon="📢")

def formatar_data_br(data_str):
    if isinstance(data_str, str):
        try:
            data_obj = datetime.strptime(data_str, '%Y-%m-%d')
            return data_obj.strftime('%d/%m/%Y')
        except:
            return data_str
    elif isinstance(data_str, datetime):
        return data_str.strftime('%d/%m/%Y')
    return data_str

def show_cache_stats():
    """Mostra estatísticas do cache em um expander."""
    stats = _sheets_cache.get_stats()
    with st.expander("📊 Estatísticas de Cache", expanded=False):
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Cache Hits", stats["hits"])
        with col2:
            st.metric("Cache Misses", stats["misses"])
        with col3:
            st.metric("Hit Ratio", f"{stats['hit_ratio']:.1%}")
        with col4:
            st.metric("Entradas", stats["cache_size"])
        
        if st.button("🧹 Limpar Cache", use_container_width=True):
            _sheets_cache.invalidate()
            st.success("Cache limpo com sucesso!")
            st.rerun()

# ==================== HEADER COM BOTÕES DE LOGOUT, RECARREGAR E CACHE ====================
col_logo, col_reload, col_cache, col_logout = st.columns([5, 1, 1, 1])
with col_logo:
    st.markdown("""
    <div class="dashboard-header animate-in" style="margin-top: -1rem;">
        <h1 class="dashboard-title">💰 Dashboard Financeiro</h1>
        <p class="dashboard-subtitle">Controle completo da sua vida financeira</p>
    </div>
    """, unsafe_allow_html=True)
with col_reload:
    st.markdown("<br><br>", unsafe_allow_html=True)
    if st.button("🔄 Recarregar", use_container_width=True):
        _sheets_cache.invalidate(f"user_data_{st.session_state.email}")
        st.rerun()
with col_cache:
    st.markdown("<br><br>", unsafe_allow_html=True)
    if st.button("📊 Cache", use_container_width=True):
        st.session_state.show_cache_stats = not st.session_state.show_cache_stats
        st.rerun()
with col_logout:
    st.markdown("<br><br>", unsafe_allow_html=True)
    if st.button("🚪 Sair", use_container_width=True):
        _sheets_cache.invalidate()  # Limpa todo cache ao sair
        st.session_state.authenticated = False
        st.session_state.email = None
        st.session_state.dados = {"renda_mensal": 0, "gastos": []}
        st.session_state.login_error = None
        st.rerun()

# Mostra estatísticas de cache se ativado
if st.session_state.show_cache_stats:
    show_cache_stats()

# ==================== MENU SUPERIOR COM ABAS ====================
tab1, tab2, tab3, tab4 = st.tabs(["📊 Visão Geral", "💰 Adicionar Renda", "💳 Adicionar Gasto", "📋 Relatório Detalhado"])

# ==================== ABA 1: VISÃO GERAL ====================
with tab1:
    renda = st.session_state.dados['renda_mensal']
    gastos = st.session_state.dados['gastos']
    total_gastos = sum(g['valor'] for g in gastos)
    saldo = renda - total_gastos

    col_resumo1, col_resumo2, col_resumo3 = st.columns(3)
    with col_resumo1:
        st.markdown(f"""
        <div style="background: linear-gradient(145deg, #1e293b, #0f172a); padding: 1.5rem; border-radius: 15px; border: 1px solid rgba(16, 185, 129, 0.3);">
            <p style="color: #64748b; font-size: 0.875rem;">RENDA MENSAL</p>
            <p style="color: #10b981; font-size: 2rem; font-weight: 700; margin: 0;">R$ {renda:,.2f}</p>
        </div>
        """, unsafe_allow_html=True)
    with col_resumo2:
        st.markdown(f"""
        <div style="background: linear-gradient(145deg, #1e293b, #0f172a); padding: 1.5rem; border-radius: 15px; border: 1px solid rgba(239, 68, 68, 0.3);">
            <p style="color: #64748b; font-size: 0.875rem;">TOTAL GASTOS</p>
            <p style="color: #ef4444; font-size: 2rem; font-weight: 700; margin: 0;">R$ {total_gastos:,.2f}</p>
        </div>
        """, unsafe_allow_html=True)
    with col_resumo3:
        cor_saldo = "#10b981" if saldo > 0 else "#ef4444"
        st.markdown(f"""
        <div style="background: linear-gradient(145deg, #1e293b, #0f172a); padding: 1.5rem; border-radius: 15px; border: 1px solid {cor_saldo};">
            <p style="color: #64748b; font-size: 0.875rem;">SALDO</p>
            <p style="color: {cor_saldo}; font-size: 2rem; font-weight: 700; margin: 0;">R$ {saldo:,.2f}</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    df_gastos = pd.DataFrame(gastos) if gastos else pd.DataFrame()

    if renda == 0:
        st.warning("⚠️ Cadastre sua renda mensal primeiro na aba '💰 Adicionar Renda'!")
    elif df_gastos.empty:
        st.info("ℹ️ Nenhum gasto registrado. Adicione seus gastos na aba '💳 Adicionar Gasto' para ver os gráficos!")
    else:
        df_gastos['data'] = pd.to_datetime(df_gastos['data'])
        total_gastos = df_gastos['valor'].sum()
        saldo = renda - total_gastos
        percentual_gasto = (total_gastos / renda * 100) if renda > 0 else 0

        col_left, col_right = st.columns(2)
        with col_left:
            st.markdown('<div class="chart-container">', unsafe_allow_html=True)
            st.subheader("🍩 Distribuição por Categoria")
            df_cat = df_gastos.groupby('categoria')['valor'].sum().reset_index()
            colors = ['#8b5cf6', '#06b6d4', '#10b981', '#f59e0b', '#ef4444', '#ec4899', '#3b82f6', '#f97316']
            fig_donut = go.Figure(data=[go.Pie(
                labels=df_cat['categoria'],
                values=df_cat['valor'],
                hole=0.65,
                marker=dict(colors=colors, line=dict(color='#0f172a', width=2)),
                textinfo='label+percent',
                textposition='outside',
                textfont=dict(size=11, color='#e2e8f0'),
                hovertemplate='<b>%{label}</b><br>R$ %{value:,.2f}<br>%{percent}<extra></extra>'
            )])
            fig_donut.update_layout(
                showlegend=False,
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                margin=dict(t=20, b=20, l=20, r=20),
                height=350,
                annotations=[dict(
                    text=f'<b>R$<br>{total_gastos:,.0f}</b>',
                    x=0.5, y=0.5,
                    font_size=20,
                    font_color='#e2e8f0',
                    showarrow=False
                )]
            )
            st.plotly_chart(fig_donut, use_container_width=True, config={'displayModeBar': False})
            st.markdown('</div>', unsafe_allow_html=True)

        with col_right:
            st.markdown('<div class="chart-container">', unsafe_allow_html=True)
            st.subheader("📈 Evolução Temporal")
            df_tempo = df_gastos.sort_values('data')
            df_tempo_acum = df_tempo.groupby('data')['valor'].sum().cumsum().reset_index()
            fig_area = go.Figure()
            fig_area.add_trace(go.Scatter(
                x=df_tempo_acum['data'],
                y=df_tempo_acum['valor'],
                fill='tozeroy',
                fillcolor='rgba(139, 92, 246, 0.2)',
                line=dict(color='#8b5cf6', width=3),
                mode='lines+markers',
                marker=dict(size=6, color='#06b6d4', line=dict(color='#0f172a', width=2)),
                hovertemplate='%{x|%d/%m/%Y}<br>Acumulado: R$ %{y:,.2f}<extra></extra>'
            ))
            fig_area.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                xaxis=dict(showgrid=False, color='#64748b', tickformat='%d/%m/%Y'),
                yaxis=dict(showgrid=True, gridcolor='rgba(148, 163, 184, 0.1)', color='#64748b'),
                margin=dict(t=20, b=20, l=20, r=20),
                height=350,
                hovermode='x unified'
            )
            st.plotly_chart(fig_area, use_container_width=True, config={'displayModeBar': False})
            st.markdown('</div>', unsafe_allow_html=True)

        col_left2, col_right2 = st.columns(2)
        with col_left2:
            st.markdown('<div class="chart-container">', unsafe_allow_html=True)
            st.subheader("📊 Gastos por Categoria (Barras)")
            df_bar = df_cat.sort_values('valor', ascending=True)
            fig_bar = go.Figure()
            fig_bar.add_trace(go.Bar(
                y=df_bar['categoria'],
                x=df_bar['valor'],
                orientation='h',
                marker=dict(
                    color=df_bar['valor'],
                    colorscale='Viridis',
                    line=dict(color='rgba(255,255,255,0.1)', width=1)
                ),
                text=[f'R$ {v:,.0f}' for v in df_bar['valor']],
                textposition='outside',
                textfont=dict(color='#e2e8f0', size=10),
                hovertemplate='<b>%{y}</b><br>R$ %{x:,.2f}<extra></extra>'
            ))
            fig_bar.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                xaxis=dict(showgrid=True, gridcolor='rgba(148, 163, 184, 0.1)', color='#64748b'),
                yaxis=dict(showgrid=False, color='#64748b'),
                margin=dict(t=20, b=20, l=100, r=50),
                height=300,
                showlegend=False
            )
            st.plotly_chart(fig_bar, use_container_width=True, config={'displayModeBar': False})
            st.markdown('</div>', unsafe_allow_html=True)

        with col_right2:
            st.markdown('<div class="chart-container">', unsafe_allow_html=True)
            st.subheader("🎯 Comparativo Renda vs Gastos")
            fig_gauge = go.Figure(go.Indicator(
                mode="gauge+number+delta",
                value=total_gastos,
                delta={'reference': renda, 'relative': True, 'valueformat': '.1%'},
                domain={'x': [0, 1], 'y': [0, 1]},
                title={'text': "Utilização da Renda", 'font': {'size': 14, 'color': '#94a3b8'}},
                number={'font': {'size': 24, 'color': '#e2e8f0'}, 'prefix': "R$", 'valueformat': ",.0f"},
                gauge={
                    'axis': {'range': [0, renda], 'tickcolor': '#64748b'},
                    'bar': {'color': '#8b5cf6', 'thickness': 0.75},
                    'bgcolor': 'rgba(0,0,0,0)',
                    'borderwidth': 2,
                    'bordercolor': '#334155',
                    'steps': [
                        {'range': [0, renda*0.5], 'color': 'rgba(16, 185, 129, 0.2)'},
                        {'range': [renda*0.5, renda*0.8], 'color': 'rgba(245, 158, 11, 0.2)'},
                        {'range': [renda*0.8, renda], 'color': 'rgba(239, 68, 68, 0.2)'}
                    ],
                    'threshold': {
                        'line': {'color': '#ef4444', 'width': 4},
                        'thickness': 0.8,
                        'value': renda
                    }
                }
            ))
            fig_gauge.update_layout(
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                margin=dict(t=50, b=20, l=20, r=20),
                height=300,
                font=dict(color='#e2e8f0')
            )
            st.plotly_chart(fig_gauge, use_container_width=True, config={'displayModeBar': False})
            st.markdown('</div>', unsafe_allow_html=True)

        # Radar
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        st.subheader("🕸️ Análise de Padrões de Gasto (% da Renda)")
        categorias_radar = ['Alimentação', 'Transporte', 'Lazer', 'Moradia', 'Saúde', 'Educação', 'Outros']
        valores_sugeridos = [15, 10, 5, 30, 10, 10, 5]
        valores_reais_percent = []
        valores_reais_valor = []
        for cat in categorias_radar:
            valor_cat = df_gastos[df_gastos['categoria'] == cat]['valor'].sum()
            valores_reais_valor.append(valor_cat)
            if renda > 0:
                percent = (valor_cat / renda) * 100
            else:
                percent = 0
            valores_reais_percent.append(min(percent, 100))

        categorias_fechado = categorias_radar + [categorias_radar[0]]
        valores_reais_fechado = valores_reais_percent + [valores_reais_percent[0]]
        valores_sugeridos_fechado = valores_sugeridos + [valores_sugeridos[0]]

        fig_radar = go.Figure()
        fig_radar.add_trace(go.Scatterpolar(
            r=valores_reais_fechado,
            theta=categorias_fechado,
            fill='toself',
            fillcolor='rgba(139, 92, 246, 0.3)',
            line=dict(color='#8b5cf6', width=3),
            marker=dict(size=6, color='#06b6d4', line=dict(color='#0f172a', width=1)),
            name='Seus gastos (% da renda)',
            hovertemplate='<b>%{theta}</b><br>R$ %{customdata:,.2f} (%{r:.1f}% da renda)<extra></extra>',
            customdata=valores_reais_valor + [valores_reais_valor[0]]
        ))
        fig_radar.add_trace(go.Scatterpolar(
            r=[30] * len(categorias_fechado),
            theta=categorias_fechado,
            fill='none',
            line=dict(color='#ef4444', width=2, dash='dash'),
            name='Limite de alerta (30%)'
        ))
        fig_radar.add_trace(go.Scatterpolar(
            r=valores_sugeridos_fechado,
            theta=categorias_fechado,
            fill='none',
            line=dict(color='#10b981', width=2, dash='dot'),
            name='Referência sugerida'
        ))
        fig_radar.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, 100],
                    color='#64748b',
                    gridcolor='rgba(148, 163, 184, 0.2)',
                    tickfont=dict(size=10),
                    ticksuffix='%'
                ),
                angularaxis=dict(color='#94a3b8', gridcolor='rgba(148, 163, 184, 0.2)'),
                bgcolor='rgba(0,0,0,0)'
            ),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            showlegend=True,
            legend=dict(
                orientation='h',
                yanchor='bottom',
                y=-0.25,
                xanchor='center',
                x=0.5,
                font=dict(color='#94a3b8')
            ),
            margin=dict(t=50, b=80, l=50, r=50),
            height=450
        )
        st.plotly_chart(fig_radar, use_container_width=True, config={'displayModeBar': False})
        st.markdown("""
        <p style="color: #94a3b8; font-size: 0.875rem; text-align: center;">
            🔍 O gráfico mostra o percentual da sua renda gasto em cada categoria. 
            A linha vermelha tracejada indica 30% (limite de alerta por categoria). 
            A linha verde pontilhada é uma referência sugerida baseada na regra 50-30-20.
        </p>
        """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Gastos por forma de pagamento
        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
        st.subheader("💳 Gastos por Forma de Pagamento")
        if 'forma_pagamento' in df_gastos.columns:
            df_pagamento = df_gastos.groupby('forma_pagamento')['valor'].sum().reset_index()
            df_pagamento = df_pagamento.sort_values('valor', ascending=False)
            fig_pagamento = px.bar(
                df_pagamento,
                x='forma_pagamento',
                y='valor',
                text='valor',
                template='plotly_dark',
                color_discrete_sequence=['#8b5cf6']
            )
            fig_pagamento.update_traces(
                texttemplate='R$ %{text:,.2f}',
                textposition='outside',
                marker=dict(line=dict(width=0))
            )
            fig_pagamento.update_layout(
                showlegend=False,
                height=400,
                margin=dict(l=20, r=20, t=40, b=20),
                plot_bgcolor='rgba(0,0,0,0)',
                paper_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#e2e8f0'),
                xaxis=dict(title='', color='#64748b'),
                yaxis=dict(title='Valor (R$)', color='#64748b', gridcolor='rgba(148, 163, 184, 0.1)')
            )
            st.plotly_chart(fig_pagamento, use_container_width=True, config={'displayModeBar': False})
        else:
            st.info("Informação de forma de pagamento não disponível nos dados.")
        st.markdown('</div>', unsafe_allow_html=True)

# ==================== ABA 2: ADICIONAR RENDA ====================
with tab2:
    st.markdown('<div class="form-container animate-in">', unsafe_allow_html=True)
    st.subheader("💰 Cadastro de Renda Mensal")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
        <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 15px; padding: 1.5rem; margin-bottom: 1rem;">
            <h4 style="color: #10b981; margin: 0;">📈 Renda Principal</h4>
            <p style="color: #94a3b8; font-size: 0.875rem; margin-top: 0.5rem;">Informe sua renda mensal líquida</p>
        </div>
        """, unsafe_allow_html=True)
        renda_input = st.number_input(
            "Valor da Renda (R$)",
            min_value=0.0,
            value=float(st.session_state.dados['renda_mensal']),
            step=100.0,
            format="%.2f",
            help="Salário, freelas, aluguéis, etc."
        )
        fonte_renda = st.selectbox(
            "Fonte Principal",
            ["Salário", "Freelance", "Empresa Própria", "Investimentos", "Outros"]
        )
        if st.button("💾 Salvar Renda", use_container_width=True, type="primary"):
            if renda_input >= 0:
                with st.spinner("Salvando renda..."):
                    if save_renda_cached(st.session_state.email, renda_input):
                        notificar_sucesso(
                            f"Renda de R$ {renda_input:,.2f} registrada",
                            f"Fonte: {fonte_renda} | Saldo atualizado"
                        )
                        st.session_state.ultima_acao = "renda_salva"
                    else:
                        notificar_erro("Erro ao salvar renda na planilha", "Tente novamente mais tarde.")
            else:
                notificar_erro("Valor da renda deve ser maior ou igual a zero", "Digite um valor válido")
    with col2:
        st.markdown("""
        <div style="background: rgba(139, 92, 246, 0.1); border: 1px solid rgba(139, 92, 246, 0.3); border-radius: 15px; padding: 1.5rem;">
            <h4 style="color: #8b5cf6; margin: 0;">💡 Dica Profissional</h4>
            <p style="color: #94a3b8; font-size: 0.875rem; margin-top: 0.5rem;">
                Mantenha sua renda sempre atualizada para um controle preciso. 
                Inclua todas as fontes de renda regular.
            </p>
        </div>
        """, unsafe_allow_html=True)
        if renda_input > 0:
            st.markdown(f"""
            <div style="margin-top: 2rem; background: rgba(15, 23, 42, 0.5); border-radius: 15px; padding: 1rem; border: 1px solid rgba(139, 92, 246, 0.2);">
                <p style="color: #64748b; margin: 0; font-size: 0.875rem;">PREVIEW</p>
                <p style="color: #e2e8f0; font-size: 1.75rem; font-weight: 700; margin: 0.5rem 0;">
                    R$ {renda_input:,.2f}
                </p>
                <div style="display: flex; align-items: center; gap: 0.5rem;">
                    <span style="color: #10b981;">●</span>
                    <span style="color: #94a3b8; font-size: 0.875rem;">Pronto para salvar</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

# ==================== ABA 3: ADICIONAR GASTO ====================
with tab3:
    st.markdown('<div class="form-container animate-in">', unsafe_allow_html=True)
    st.subheader("💸 Registro de Novo Gasto")
    categorias = {
        "Alimentação": "🍔",
        "Transporte": "🚗",
        "Lazer": "🎮",
        "Moradia": "🏠",
        "Saúde": "⚕️",
        "Educação": "📚",
        "Vestuário": "👕",
        "Tecnologia": "💻",
        "Outros": "📦"
    }
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
        <div style="background: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 15px; padding: 1.5rem; margin-bottom: 1rem;">
            <h4 style="color: #ef4444; margin: 0;">📝 Detalhes do Gasto</h4>
        </div>
        """, unsafe_allow_html=True)
        descricao = st.text_input("Descrição", placeholder="Ex: Supermercado Extra")
        cat_selecionada = st.selectbox(
            "Categoria",
            list(categorias.keys()),
            format_func=lambda x: f"{categorias[x]} {x}"
        )
        valor_gasto = st.number_input(
            "Valor (R$)",
            min_value=0.01,
            step=10.0,
            format="%.2f"
        )
        data_gasto = st.date_input("Data", datetime.now(), format="DD/MM/YYYY")
        forma_pagamento = st.selectbox(
            "Forma de Pagamento",
            ["Cartão de Crédito", "Cartão de Débito", "PIX", "Dinheiro", "Boleto"]
        )
    with col2:
        st.markdown("""
        <div style="background: rgba(245, 158, 11, 0.1); border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 15px; padding: 1.5rem; margin-bottom: 1rem;">
            <h4 style="color: #fbbf24; margin: 0;">⚠️ Importante</h4>
            <p style="color: #94a3b8; font-size: 0.875rem; margin-top: 0.5rem;">
                Registre todos os gastos, mesmo os pequenos. 
                Pequenas despesas somam grandes valores no final do mês!
            </p>
        </div>
        """, unsafe_allow_html=True)
        if valor_gasto > 0:
            data_formatada = data_gasto.strftime('%d/%m/%Y')
            st.markdown(f"""
            <div style="background: rgba(15, 23, 42, 0.8); border-radius: 20px; padding: 2rem; text-align: center; border: 2px solid #ef4444;">
                <p style="color: #64748b; margin: 0; font-size: 0.875rem;">VALOR DO GASTO</p>
                <p style="color: #ef4444; font-size: 2.5rem; font-weight: 700; margin: 1rem 0;">
                    - R$ {valor_gasto:,.2f}
                </p>
                <p style="color: #94a3b8; margin: 0.5rem 0; font-size: 0.875rem;">📅 {data_formatada}</p>
                <span class="category-badge cat-{cat_selecionada.lower()}">{categorias[cat_selecionada]} {cat_selecionada}</span>
            </div>
            """, unsafe_allow_html=True)
        renda_atual = st.session_state.dados['renda_mensal']
        gastos_atuais = sum(g['valor'] for g in st.session_state.dados['gastos'])
        novo_total = gastos_atuais + valor_gasto
        percentual = (novo_total / renda_atual * 100) if renda_atual > 0 else 0
        if renda_atual > 0:
            cor_impacto = "#10b981" if percentual < 70 else "#fbbf24" if percentual < 90 else "#ef4444"
            st.markdown(f"""
            <div style="margin-top: 1.5rem; padding: 1rem; background: rgba(15, 23, 42, 0.5); border-radius: 15px;">
                <p style="color: #64748b; margin: 0; font-size: 0.875rem;">IMPACTO NO ORÇAMENTO</p>
                <p style="color: {cor_impacto}; font-size: 1.25rem; font-weight: 700; margin: 0.5rem 0;">
                    {percentual:.1f}% da renda
                </p>
                <div class="progress-container">
                    <div class="progress-bar" style="width: {min(percentual, 100)}%; opacity: 0.8;"></div>
                </div>
            </div>
            """, unsafe_allow_html=True)
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        salvar_click = st.button("💾 Salvar Gasto", use_container_width=True, type="primary")
    with col_btn2:
        limpar_click = st.button("🗑️ Limpar", use_container_width=True)
    if salvar_click:
        if descricao and valor_gasto > 0:
            with st.spinner("Salvando gasto..."):
                novo_gasto = {
                    'descricao': descricao,
                    'categoria': cat_selecionada,
                    'valor': valor_gasto,
                    'data': data_gasto.strftime('%Y-%m-%d'),
                    'forma_pagamento': forma_pagamento,
                    'timestamp': datetime.now().isoformat()
                }
                gasto_id = add_gasto_cached(st.session_state.email, novo_gasto)
                if gasto_id:
                    notificar_sucesso(
                        f"Gasto de R$ {valor_gasto:,.2f} registrado",
                        f"{cat_selecionada} • {forma_pagamento}"
                    )
                else:
                    notificar_erro("Erro ao salvar gasto na planilha", "Tente novamente mais tarde.")
        else:
            notificar_erro("Preencha todos os campos obrigatórios", "Descrição e valor são necessários")
    if limpar_click:
        notificar_info("Formulário limpo")
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# ==================== ABA 4: RELATÓRIO DETALHADO ====================
with tab4:
    renda = st.session_state.dados['renda_mensal']
    gastos = st.session_state.dados['gastos']
    df_gastos = pd.DataFrame(gastos) if gastos else pd.DataFrame()
    st.markdown('<div class="chart-container animate-in">', unsafe_allow_html=True)
    st.subheader("📋 Relatório Completo de Gastos")
    if not df_gastos.empty:
        df_gastos['data'] = pd.to_datetime(df_gastos['data'])
        total_gastos = df_gastos['valor'].sum()
        saldo = renda - total_gastos
        media_gasto = df_gastos['valor'].mean()
        maior_gasto_idx = df_gastos['valor'].idxmax()
        maior_gasto = df_gastos.loc[maior_gasto_idx]
        col_res1, col_res2, col_res3, col_res4 = st.columns(4)
        with col_res1:
            st.markdown(f"""
            <div style="background: linear-gradient(145deg, #1e293b, #0f172a); border-radius: 15px; padding: 1rem; border-left: 4px solid #10b981;">
                <p style="color: #64748b; margin: 0; font-size: 0.75rem;">RENDA TOTAL</p>
                <p style="color: #10b981; font-size: 1.5rem; font-weight: 700; margin: 0.5rem 0;">R$ {renda:,.2f}</p>
            </div>
            """, unsafe_allow_html=True)
        with col_res2:
            st.markdown(f"""
            <div style="background: linear-gradient(145deg, #1e293b, #0f172a); border-radius: 15px; padding: 1rem; border-left: 4px solid #ef4444;">
                <p style="color: #64748b; margin: 0; font-size: 0.75rem;">TOTAL GASTOS</p>
                <p style="color: #ef4444; font-size: 1.5rem; font-weight: 700; margin: 0.5rem 0;">R$ {total_gastos:,.2f}</p>
            </div>
            """, unsafe_allow_html=True)
        with col_res3:
            cor_saldo = "#06b6d4" if saldo > 0 else "#ef4444"
            st.markdown(f"""
            <div style="background: linear-gradient(145deg, #1e293b, #0f172a); border-radius: 15px; padding: 1rem; border-left: 4px solid {cor_saldo};">
                <p style="color: #64748b; margin: 0; font-size: 0.75rem;">SALDO</p>
                <p style="color: {cor_saldo}; font-size: 1.5rem; font-weight: 700; margin: 0.5rem 0;">R$ {saldo:,.2f}</p>
            </div>
            """, unsafe_allow_html=True)
        with col_res4:
            st.markdown(f"""
            <div style="background: linear-gradient(145deg, #1e293b, #0f172a); border-radius: 15px; padding: 1rem; border-left: 4px solid #8b5cf6;">
                <p style="color: #64748b; margin: 0; font-size: 0.75rem;">TRANSAÇÕES</p>
                <p style="color: #8b5cf6; font-size: 1.5rem; font-weight: 700; margin: 0.5rem 0;">{len(df_gastos)}</p>
            </div>
            """, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        st.subheader("📄 Lista Completa de Transações")
        df_display = df_gastos.copy()
        df_display['Data'] = df_display['data'].apply(lambda x: x.strftime('%d/%m/%Y') if isinstance(x, datetime) else x)
        df_display['Valor Formatado'] = df_display['valor'].apply(lambda x: f"R$ {x:,.2f}")
        df_display = df_display[['Data', 'descricao', 'categoria', 'forma_pagamento', 'valor', 'Valor Formatado']]
        df_display.columns = ['Data', 'Descrição', 'Categoria', 'Pagamento', 'Valor', 'Valor Formatado']
        altura_tabela = min(35 * len(df_display) + 40, 600)
        st.dataframe(
            df_display[['Data', 'Descrição', 'Categoria', 'Pagamento', 'Valor Formatado']],
            column_config={
                "Data": st.column_config.TextColumn("📅 Data", width="small"),
                "Descrição": st.column_config.TextColumn("📝 Descrição", width="large"),
                "Categoria": st.column_config.TextColumn("🏷️ Categoria", width="medium"),
                "Pagamento": st.column_config.TextColumn("💳 Pagamento", width="medium"),
                "Valor Formatado": st.column_config.TextColumn("💰 Valor", width="small")
            },
            hide_index=True,
            use_container_width=True,
            height=altura_tabela
        )
        st.markdown("---")
        st.subheader("📊 Estatísticas Detalhadas")
        col_stat1, col_stat2, col_stat3 = st.columns(3)
        with col_stat1:
            data_maior_gasto = maior_gasto['data'].strftime('%d/%m/%Y') if isinstance(maior_gasto['data'], datetime) else formatar_data_br(maior_gasto['data'])
            st.markdown(f"""
            <div style="background: rgba(239, 68, 68, 0.1); border-radius: 15px; padding: 1.5rem; border: 1px solid rgba(239, 68, 68, 0.3);">
                <p style="color: #64748b; margin: 0; font-size: 0.875rem;">🔥 MAIOR GASTO</p>
                <p style="color: #f87171; font-size: 1.5rem; font-weight: 700; margin: 0.5rem 0;">R$ {maior_gasto['valor']:,.2f}</p>
                <p style="color: #94a3b8; margin: 0; font-size: 0.875rem;">{maior_gasto['descricao']}</p>
                <p style="color: #64748b; margin: 0.25rem 0 0 0; font-size: 0.75rem;">📅 {data_maior_gasto}</p>
            </div>
            """, unsafe_allow_html=True)
        with col_stat2:
            st.markdown(f"""
            <div style="background: rgba(139, 92, 246, 0.1); border-radius: 15px; padding: 1.5rem; border: 1px solid rgba(139, 92, 246, 0.3);">
                <p style="color: #64748b; margin: 0; font-size: 0.875rem;">📊 MÉDIA POR GASTO</p>
                <p style="color: #a78bfa; font-size: 1.5rem; font-weight: 700; margin: 0.5rem 0;">R$ {media_gasto:,.2f}</p>
                <p style="color: #94a3b8; margin: 0; font-size: 0.875rem;">Por transação</p>
                <p style="color: #64748b; margin: 0.25rem 0 0 0; font-size: 0.75rem;">{len(df_gastos)} gastos registrados</p>
            </div>
            """, unsafe_allow_html=True)
        with col_stat3:
            cat_stats = df_gastos.groupby('categoria')['valor'].agg(['sum', 'count'])
            cat_top = cat_stats['sum'].idxmax()
            val_cat_top = cat_stats['sum'].max()
            qtd_cat_top = cat_stats.loc[cat_top, 'count']
            st.markdown(f"""
            <div style="background: rgba(245, 158, 11, 0.1); border-radius: 15px; padding: 1.5rem; border: 1px solid rgba(245, 158, 11, 0.3);">
                <p style="color: #64748b; margin: 0; font-size: 0.875rem;">🏆 CATEGORIA TOP</p>
                <p style="color: #fbbf24; font-size: 1.5rem; font-weight: 700; margin: 0.5rem 0;">{cat_top}</p>
                <p style="color: #94a3b8; margin: 0; font-size: 0.875rem;">R$ {val_cat_top:,.2f} total</p>
                <p style="color: #64748b; margin: 0.25rem 0 0 0; font-size: 0.75rem;">{qtd_cat_top} transações</p>
            </div>
            """, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        st.subheader("📈 Resumo por Categoria")
        df_resumo_cat = df_gastos.groupby('categoria').agg({'valor': ['sum', 'count', 'mean']}).round(2)
        df_resumo_cat.columns = ['Total', 'Quantidade', 'Média']
        df_resumo_cat = df_resumo_cat.sort_values('Total', ascending=False).reset_index()
        df_resumo_cat['% do Total'] = (df_resumo_cat['Total'] / total_gastos * 100).round(1)
        df_resumo_display = df_resumo_cat.copy()
        df_resumo_display['Total'] = df_resumo_display['Total'].apply(lambda x: f"R$ {x:,.2f}")
        df_resumo_display['Média'] = df_resumo_display['Média'].apply(lambda x: f"R$ {x:,.2f}")
        df_resumo_display['% do Total'] = df_resumo_display['% do Total'].apply(lambda x: f"{x}%")
        st.dataframe(
            df_resumo_display,
            column_config={
                "categoria": st.column_config.TextColumn("Categoria", width="medium"),
                "Total": st.column_config.TextColumn("Total Gasto", width="small"),
                "Quantidade": st.column_config.NumberColumn("Qtd.", width="small"),
                "Média": st.column_config.TextColumn("Média", width="small"),
                "% do Total": st.column_config.TextColumn("% do Total", width="small")
            },
            hide_index=True,
            use_container_width=True
        )
        st.markdown("<br>", unsafe_allow_html=True)
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            df_export = df_gastos.copy()
            df_export['data'] = df_export['data'].apply(lambda x: x.strftime('%d/%m/%Y') if isinstance(x, datetime) else formatar_data_br(x))
            csv = df_export.to_csv(index=False).encode('utf-8')
            download_click = st.download_button(
                label="📥 Exportar CSV",
                data=csv,
                file_name=f'relatorio_gastos_{datetime.now().strftime("%d%m%Y")}.csv',
                mime='text/csv',
                use_container_width=True
            )
            if download_click:
                notificar_sucesso("Relatório exportado", f"Arquivo: relatorio_gastos_{datetime.now().strftime('%d%m%Y')}.csv")
        with col_btn2:
            excel_click = st.button("📊 Exportar Excel", use_container_width=True)
            if excel_click:
                notificar_info("Funcionalidade Excel em desenvolvimento")
        col_center1, col_center2, col_center3 = st.columns([1, 2, 1])
        with col_center2:
            limpar_click = st.button("🗑️ Limpar Todos os Dados", use_container_width=True)
            if limpar_click:
                st.session_state.confirmar_limpeza = True
        if st.session_state.get('confirmar_limpeza'):
            st.warning("⚠️ Esta ação não pode ser desfeita e removerá todos os seus dados da planilha!")
            col_conf1, col_conf2 = st.columns(2)
            with col_conf1:
                if st.button("✅ Sim, limpar tudo", use_container_width=True):
                    with st.spinner("Limpando dados..."):
                        if delete_all_user_data_cached(st.session_state.email):
                            notificar_sucesso("Todos os dados foram removidos", "Sistema resetado com sucesso")
                        else:
                            notificar_erro("Erro ao limpar dados", "Tente novamente mais tarde")
                    st.session_state.confirmar_limpeza = False
                    time.sleep(1)
                    st.rerun()
            with col_conf2:
                if st.button("❌ Cancelar", use_container_width=True):
                    st.session_state.confirmar_limpeza = False
                    notificar_info("Operação cancelada")
                    st.rerun()
    else:
        st.info("ℹ️ Nenhum gasto registrado ainda. Adicione gastos para gerar o relatório completo.")
    st.markdown('</div>', unsafe_allow_html=True)

# ==================== FOOTER ====================
st.markdown("""
<div style="text-align: center; padding: 2rem 1rem; color: #64748b; font-size: 0.875rem; margin-top: 2rem;">
    <p style="margin: 0;">💰 Dashboard Financeiro</p>
    <p style="margin: 0.5rem 0 0 0; font-size: 0.75rem;">Desenvolvido com Streamlit</p>
</div>
""", unsafe_allow_html=True)
