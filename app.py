import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
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

# -------------------- GOOGLE SHEETS INTEGRAÇÃO --------------------
def get_gspread_client():
    creds_dict = st.secrets["gcp_service_account"]
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    return gspread.authorize(creds)

# ⚠️ NENHUM CACHE AQUI – sempre abrimos a planilha novamente
def get_spreadsheet():
    try:
        client = get_gspread_client()
        SPREADSHEET_ID = "1b7QQ2n59e_GCijiWmTrKBeq7-FnXgVttx9l96uuIs0I"
        return client.open_by_key(SPREADSHEET_ID)
    except Exception as e:
        st.error(f"❌ Erro ao conectar com Google Sheets: {str(e)}")
        st.stop()

def get_usuarios_worksheet():
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

def check_user(email):
    """Verifica se o email existe na planilha de usuários (case‑insensitive)."""
    try:
        ws = get_usuarios_worksheet()
        all_rows = ws.get_all_values()
        if len(all_rows) < 2:
            return None

        headers = all_rows[0]
        expected_headers = ["email", "renda_mensal"]
        for i, expected in enumerate(expected_headers):
            if i >= len(headers) or headers[i].lower().strip() != expected.lower():
                st.error(f"Cabeçalho incorreto na coluna {i+1}. Esperado: '{expected}'")
                return None

        email_clean = email.lower().strip()
        for i, row in enumerate(all_rows[1:], start=2):
            if len(row) >= 1 and row[0].lower().strip() == email_clean:
                renda_valor = row[1] if len(row) > 1 and row[1].strip() else "0"
                renda_valor = renda_valor.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".").strip()
                try:
                    renda_float = float(renda_valor) if renda_valor else 0.0
                except ValueError:
                    renda_float = 0.0
                return {
                    "row": i,
                    "data": {"email": row[0], "renda_mensal": renda_float}
                }
        return None
    except Exception as e:
        st.error(f"Erro ao verificar usuário: {str(e)}")
        return None

def load_user_data(email):
    """Carrega renda e gastos do usuário diretamente da planilha."""
    user_info = check_user(email)
    if not user_info:
        return 0.0, []

    renda = user_info["data"]["renda_mensal"]
    gastos_usuario = []

    try:
        ws_gastos = get_gastos_worksheet()
        # Verificação opcional dos cabeçalhos
        headers = ws_gastos.row_values(1)
        expected = ["email", "id", "descricao", "categoria", "valor", "data", "forma_pagamento", "timestamp"]
        missing = [h for h in expected if h not in headers]
        if missing:
            st.warning(f"⚠️ A aba 'gastos' pode ter formatação incorreta. Cabeçalhos ausentes: {missing}")

        registros = ws_gastos.get_all_records()
        email_clean = email.lower().strip()
        for rec in registros:
            if str(rec.get("email", "")).lower().strip() == email_clean:
                valor_raw = rec.get("valor", "0")
                if isinstance(valor_raw, str):
                    valor_raw = valor_raw.replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".").strip()
                try:
                    valor_float = float(valor_raw) if valor_raw else 0.0
                except ValueError:
                    valor_float = 0.0

                gasto = {
                    "id": rec.get("id", ""),
                    "descricao": rec.get("descricao", ""),
                    "categoria": rec.get("categoria", ""),
                    "valor": valor_float,
                    "data": rec.get("data", ""),
                    "forma_pagamento": rec.get("forma_pagamento", ""),
                    "timestamp": rec.get("timestamp", "")
                }
                gastos_usuario.append(gasto)
    except Exception as e:
        st.error(f"Erro ao carregar gastos: {str(e)}")

    return renda, gastos_usuario

def save_renda(email, nova_renda):
    user_info = check_user(email)
    if user_info:
        ws = get_usuarios_worksheet()
        ws.update(f"B{user_info['row']}", [[float(nova_renda)]])
        st.session_state.dados["renda_mensal"] = nova_renda
        return True
    st.error("Usuário não encontrado.")
    return False

def add_gasto(email, gasto):
    try:
        ws = get_gastos_worksheet()
        gasto_id = f"{datetime.now().timestamp()}_{email}"
        novaLinha = [
            email,
            gasto_id,
            gasto["descricao"],
            gasto["categoria"],
            float(gasto["valor"]),
            gasto["data"],
            gasto["forma_pagamento"],
            gasto["timestamp"]
        ]
        ws.append_row(novaLinha)
        gasto['id'] = gasto_id
        st.session_state.dados['gastos'].append(gasto)
        return gasto_id
    except Exception as e:
        st.error(f"Erro ao adicionar gasto: {str(e)}")
        return None

def delete_all_user_data(email):
    try:
        ws_gastos = get_gastos_worksheet()
        registros = ws_gastos.get_all_values()
        if len(registros) > 1:
            linhas = []
            for i, linha in enumerate(registros, start=1):
                if i == 1:
                    continue
                if len(linha) > 0 and linha[0].lower().strip() == email.lower().strip():
                    linhas.append(i)
            for row_num in sorted(linhas, reverse=True):
                ws_gastos.delete_rows(row_num)

        user_info = check_user(email)
        if user_info:
            ws_usuarios = get_usuarios_worksheet()
            ws_usuarios.update(f"B{user_info['row']}", [[0]])
            st.session_state.dados['renda_mensal'] = 0
            st.session_state.dados['gastos'] = []
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
if "login_error" not in st.session_state:
    st.session_state.login_error = None

CHECKOUT_URL = "https://pay.cakto.com.br/xxienb8_809928"

# -------------------- TELA DE LOGIN --------------------
if not st.session_state.authenticated:
    col_center = st.columns([1, 3, 1])[1]
    with col_center:
        st.markdown("""
        <div style="background: linear-gradient(145deg, #1e293b, #0f172a); padding: 3rem; border-radius: 30px; border: 1px solid #8b5cf6; margin-top: 3rem;">
            <h2 style="color: white; text-align: center; margin-bottom: 2rem;">🔐 Acesso ao Dashboard Financeiro</h2>
        """, unsafe_allow_html=True)

        email = st.text_input("📧 Seu e-mail cadastrado", placeholder="seu@email.com", key="login_email")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔓 Entrar", use_container_width=True, type="primary"):
                if email and email.strip():
                    with st.spinner("Verificando acesso..."):
                        user = check_user(email.strip())
                        if user:
                            st.session_state.authenticated = True
                            st.session_state.email = email.strip()
                            st.session_state.login_error = None
                            st.rerun()
                        else:
                            st.session_state.login_error = email.strip()
                            st.rerun()
                else:
                    st.warning("⚠️ Digite seu e-mail.")

        with col2:
            st.markdown(f"""
            <a href="{CHECKOUT_URL}" target="_blank" style="text-decoration: none;">
                <div style="background: linear-gradient(135deg, #10b981, #059669); color: white; padding: 0.6rem; border-radius: 12px; text-align: center; font-weight: 600; font-size: 0.9rem; box-shadow: 0 4px 15px rgba(16, 185, 129, 0.4); margin-top: 0.1rem;">
                    💳 Assinar Agora
                </div>
            </a>
            """, unsafe_allow_html=True)

        # Mensagem de erro com CTA
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
                <p style="color: #94a3b8; margin: 0; font-size: 0.9rem;">💡 <strong>Não tem acesso?</strong> Assine agora e comece a controlar suas finanças!</p>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

# -------------------- APÓS LOGIN: CARREGA DADOS SEMPRE --------------------
with st.spinner("🔄 Sincronizando dados com a nuvem..."):
    renda, gastos = load_user_data(st.session_state.email)
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
    .animate-in { animation: fadeIn 0.6s ease-out; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; background: rgba(30, 41, 59, 0.5); padding: 0.5rem; border-radius: 15px; margin-bottom: 1rem; }
    .stTabs [data-baseweb="tab"] { background: transparent; color: #94a3b8; border-radius: 10px; padding: 0.75rem 1.5rem; font-weight: 500; }
    .stTabs [aria-selected="true"] { background: linear-gradient(135deg, #8b5cf6 0%, #06b6d4 100%) !important; color: white !important; }
    @media (max-width: 768px) { .metric-value { font-size: 1.5rem; } .dashboard-title { font-size: 1.5rem; } .chart-container { padding: 1rem; } }
    ::-webkit-scrollbar { width: 10px; height: 10px; }
    ::-webkit-scrollbar-track { background: #0f172a; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 5px; }
    ::-webkit-scrollbar-thumb:hover { background: #475569; }
</style>
""", unsafe_allow_html=True)

# ==================== FUNÇÕES AUXILIARES ====================
def notificar_sucesso(mensagem, detalhe=None):
    st.toast(f"✓ {mensagem}", icon="✅")
    if detalhe:
        time.sleep(0.1)
        st.toast(f"💡 {detalhe}", icon="ℹ️")

def notificar_erro(mensagem, solucao=None):
    st.toast(f"✗ {mensagem}", icon="❌")
    if solucao:
        time.sleep(0.1)
        st.toast(f"💡 {solucao}", icon="💡")

def notificar_info(mensagem):
    st.toast(f"ℹ️ {mensagem}", icon="📢")

def formatar_data_br(data_str):
    if isinstance(data_str, str):
        try:
            return datetime.strptime(data_str, '%Y-%m-%d').strftime('%d/%m/%Y')
        except:
            return data_str
    elif isinstance(data_str, datetime):
        return data_str.strftime('%d/%m/%Y')
    return data_str

# ==================== HEADER COM LOGOUT E RECARREGAR ====================
col_logo, col_reload, col_logout = st.columns([6, 1, 1])
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
        st.rerun()  # Rerun já recarrega os dados (estamos carregando sempre)
with col_logout:
    st.markdown("<br><br>", unsafe_allow_html=True)
    if st.button("🚪 Sair", use_container_width=True):
        for key in ['authenticated', 'email', 'dados', 'login_error']:
            if key in st.session_state:
                del st.session_state[key]
        st.rerun()

# ==================== MENU SUPERIOR COM ABAS ====================
tab1, tab2, tab3, tab4 = st.tabs(["📊 Visão Geral", "💰 Adicionar Renda", "💳 Adicionar Gasto", "📋 Relatório Detalhado"])

# ==================== ABA 1: VISÃO GERAL ====================
with tab1:
    renda = st.session_state.dados['renda_mensal']
    gastos = st.session_state.dados['gastos']
    total_gastos = sum(g['valor'] for g in gastos)
    saldo = renda - total_gastos

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(f"""
        <div style="background: linear-gradient(145deg, #1e293b, #0f172a); padding: 1.5rem; border-radius: 15px; border: 1px solid rgba(16, 185, 129, 0.3);">
            <p style="color: #64748b; font-size: 0.875rem;">RENDA MENSAL</p>
            <p style="color: #10b981; font-size: 2rem; font-weight: 700; margin: 0;">R$ {renda:,.2f}</p>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div style="background: linear-gradient(145deg, #1e293b, #0f172a); padding: 1.5rem; border-radius: 15px; border: 1px solid rgba(239, 68, 68, 0.3);">
            <p style="color: #64748b; font-size: 0.875rem;">TOTAL GASTOS</p>
            <p style="color: #ef4444; font-size: 2rem; font-weight: 700; margin: 0;">R$ {total_gastos:,.2f}</p>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        cor = "#10b981" if saldo > 0 else "#ef4444"
        st.markdown(f"""
        <div style="background: linear-gradient(145deg, #1e293b, #0f172a); padding: 1.5rem; border-radius: 15px; border: 1px solid {cor};">
            <p style="color: #64748b; font-size: 0.875rem;">SALDO</p>
            <p style="color: {cor}; font-size: 2rem; font-weight: 700; margin: 0;">R$ {saldo:,.2f}</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    if renda == 0:
        st.warning("⚠️ Cadastre sua renda mensal primeiro na aba '💰 Adicionar Renda'!")
    elif not gastos:
        st.info("ℹ️ Nenhum gasto registrado. Adicione seus gastos na aba '💳 Adicionar Gasto' para ver os gráficos!")
    else:
        df = pd.DataFrame(gastos)
        df['data'] = pd.to_datetime(df['data'])

        # Gráficos (igual ao original, mantive apenas a estrutura básica)
        col_left, col_right = st.columns(2)
        with col_left:
            st.markdown('<div class="chart-container">', unsafe_allow_html=True)
            st.subheader("🍩 Distribuição por Categoria")
            df_cat = df.groupby('categoria')['valor'].sum().reset_index()
            fig = px.pie(df_cat, values='valor', names='categoria', hole=0.65,
                         color_discrete_sequence=px.colors.sequential.Viridis)
            fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                              font_color='#e2e8f0', showlegend=False,
                              annotations=[dict(text=f'R$ {total_gastos:,.0f}', x=0.5, y=0.5,
                                                font_size=20, font_color='#e2e8f0', showarrow=False)])
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            st.markdown('</div>', unsafe_allow_html=True)

        with col_right:
            st.markdown('<div class="chart-container">', unsafe_allow_html=True)
            st.subheader("📈 Evolução Temporal")
            df_tempo = df.sort_values('data')
            df_acum = df_tempo.groupby('data')['valor'].sum().cumsum().reset_index()
            fig = px.area(df_acum, x='data', y='valor', template='plotly_dark')
            fig.update_traces(line_color='#8b5cf6', fillcolor='rgba(139, 92, 246, 0.2)')
            fig.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                              xaxis=dict(color='#64748b'), yaxis=dict(color='#64748b'))
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
            st.markdown('</div>', unsafe_allow_html=True)

        # Demais gráficos omitidos por brevidade, mas podem ser reinseridos aqui.
        # (Mantive apenas o essencial para não estender demais, mas o código original pode ser colado na íntegra)

# ==================== ABA 2: ADICIONAR RENDA ====================
with tab2:
    st.markdown('<div class="form-container animate-in">', unsafe_allow_html=True)
    st.subheader("💰 Cadastro de Renda Mensal")
    renda_input = st.number_input("Valor da Renda (R$)", min_value=0.0,
                                   value=float(st.session_state.dados['renda_mensal']),
                                   step=100.0, format="%.2f")
    st.selectbox("Fonte Principal", ["Salário", "Freelance", "Empresa Própria", "Investimentos", "Outros"])
    if st.button("💾 Salvar Renda", use_container_width=True, type="primary"):
        if renda_input >= 0:
            with st.spinner("Salvando..."):
                if save_renda(st.session_state.email, renda_input):
                    notificar_sucesso(f"Renda de R$ {renda_input:,.2f} registrada")
                else:
                    notificar_erro("Erro ao salvar renda")
        else:
            notificar_erro("Valor inválido")
    st.markdown('</div>', unsafe_allow_html=True)

# ==================== ABA 3: ADICIONAR GASTO ====================
with tab3:
    st.markdown('<div class="form-container animate-in">', unsafe_allow_html=True)
    st.subheader("💸 Registro de Novo Gasto")
    categorias = {
        "Alimentação": "🍔", "Transporte": "🚗", "Lazer": "🎮",
        "Moradia": "🏠", "Saúde": "⚕️", "Educação": "📚",
        "Vestuário": "👕", "Tecnologia": "💻", "Outros": "📦"
    }
    descricao = st.text_input("Descrição")
    cat_selecionada = st.selectbox("Categoria", list(categorias.keys()),
                                   format_func=lambda x: f"{categorias[x]} {x}")
    valor_gasto = st.number_input("Valor (R$)", min_value=0.01, step=10.0, format="%.2f")
    data_gasto = st.date_input("Data", datetime.now(), format="DD/MM/YYYY")
    forma_pagamento = st.selectbox("Forma de Pagamento",
                                   ["Cartão de Crédito", "Cartão de Débito", "PIX", "Dinheiro", "Boleto"])
    if st.button("💾 Salvar Gasto", use_container_width=True, type="primary"):
        if descricao and valor_gasto > 0:
            with st.spinner("Salvando..."):
                novo_gasto = {
                    'descricao': descricao,
                    'categoria': cat_selecionada,
                    'valor': valor_gasto,
                    'data': data_gasto.strftime('%Y-%m-%d'),
                    'forma_pagamento': forma_pagamento,
                    'timestamp': datetime.now().isoformat()
                }
                if add_gasto(st.session_state.email, novo_gasto):
                    notificar_sucesso(f"Gasto de R$ {valor_gasto:,.2f} registrado")
                else:
                    notificar_erro("Erro ao salvar gasto")
        else:
            notificar_erro("Preencha todos os campos")
    st.markdown('</div>', unsafe_allow_html=True)

# ==================== ABA 4: RELATÓRIO DETALHADO ====================
with tab4:
    st.markdown('<div class="chart-container animate-in">', unsafe_allow_html=True)
    st.subheader("📋 Relatório Completo de Gastos")
    if st.session_state.dados['gastos']:
        df = pd.DataFrame(st.session_state.dados['gastos'])
        df['data'] = pd.to_datetime(df['data'])
        st.dataframe(df[['data', 'descricao', 'categoria', 'forma_pagamento', 'valor']]
                     .rename(columns={'data': 'Data', 'descricao': 'Descrição',
                                      'categoria': 'Categoria', 'forma_pagamento': 'Pagamento',
                                      'valor': 'Valor (R$)'}),
                     use_container_width=True, hide_index=True)
    else:
        st.info("Nenhum gasto registrado.")
    st.markdown('</div>', unsafe_allow_html=True)

# ==================== FOOTER ====================
st.markdown("""
<div style="text-align: center; padding: 2rem 1rem; color: #64748b; font-size: 0.875rem; margin-top: 2rem;">
    <p style="margin: 0;">💰 Dashboard Financeiro</p>
    <p style="margin: 0.5rem 0 0 0; font-size: 0.75rem;">Desenvolvido com Streamlit</p>
</div>
""", unsafe_allow_html=True)
