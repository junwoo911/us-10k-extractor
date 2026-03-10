import streamlit as st
import OpenDartReader
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import io
import zipfile
from datetime import datetime

# --- 페이지 기본 설정 (가장 먼저 와야 함) ---
st.set_page_config(page_title="글로벌 공시 분석 플랫폼", page_icon="🌍", layout="wide", initial_sidebar_state="expanded")

# ==========================================
# 🇺🇸 미국 공시 추출용 내부 엔진 (함수)
# ==========================================
US_HEADERS = {'User-Agent': 'MyCompanyName (myemail@gmail.com)'}

@st.cache_data(ttl=3600)
def get_cik(ticker):
    url = "https://www.sec.gov/files/company_tickers.json"
    try:
        res = requests.get(url, headers=US_HEADERS)
        data = res.json()
        ticker = ticker.upper()
        for key, val in data.items():
            if val['ticker'] == ticker:
                return str(val['cik_str']).zfill(10)
    except:
        pass
    return None

def fetch_us_filings(cik, start_year, end_year, selected_forms):
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    res = requests.get(url, headers=US_HEADERS)
    data = res.json()
    recent = data['filings']['recent']
    
    filings = []
    for i in range(len(recent['form'])):
        form = recent['form'][i]
        if form in ['10-K', '10-Q']:
            report_date = recent['reportDate'][i]
            year = int(report_date[:4])
            
            if start_year <= year <= end_year:
                acc_num = recent['accessionNumber'][i].replace('-', '')
                doc_name = recent['primaryDocument'][i]
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_num}/{doc_name}"
                filings.append({'form': form, 'year': year, 'report_date': report_date, 'url': doc_url})
                
    q_filings = [f for f in filings if f['form'] == '10-Q']
    q_filings.sort(key=lambda x: x['report_date'])
    
    quarter_map = {}
    year_counts = {}
    for f in q_filings:
        y = f['year']
        year_counts[y] = year_counts.get(y, 0) + 1
        q_num = year_counts[y] if year_counts[y] <= 3 else 3 
        quarter_map[f['url']] = f"{q_num}Q"

    final_list = []
    for f in filings:
        if f['form'] == '10-K' and '10-K' in selected_forms:
            f['q_label'] = ""
            final_list.append(f)
        elif f['form'] == '10-Q':
            q_label = quarter_map.get(f['url'], "1Q")
            if f"{q_label[0]}분기" in selected_forms:
                f['q_label'] = q_label
                final_list.append(f)
                
    return final_list

def process_us_document(ticker, url, form_type):
    res = requests.get(url, headers=US_HEADERS)
    soup = BeautifulSoup(res.content, 'html.parser')
    for s in soup(["script", "style"]): s.decompose()
    text = soup.get_text(separator='\n')
    clean_text = re.sub(r'\n\s*\n+', '\n\n', text)
    
    extracted_text = f"### {ticker} {form_type} 핵심 추출 ###\n\n"
    
    if form_type == '10-K':
        item1_pattern = re.compile(r'\n\s*ITEM\s+1\.(.*?)\n\s*ITEM\s+1B\.', re.IGNORECASE | re.DOTALL)
        item1_matches = item1_pattern.findall(clean_text)
        if item1_matches:
            extracted_text += "=== [ ITEM 1 (사업 내용) & ITEM 1A (위험 요소) ] ===\n"
            extracted_text += max(item1_matches, key=len).strip() + "\n\n"
            
        item7_pattern = re.compile(r'\n\s*ITEM\s+7\.[^\n]*MANAGEMENT[^\n]*\n(.*?)\n\s*ITEM\s+7A\.', re.IGNORECASE | re.DOTALL)
        item7_matches = item7_pattern.findall(clean_text)
        if item7_matches:
            extracted_text += "=== [ ITEM 7 (경영진의 진단 및 분석) ] ===\n"
            extracted_text += max(item7_matches, key=len).strip() + "\n\n"
            
    elif form_type == '10-Q':
        item2_pattern = re.compile(r'\n\s*ITEM\s+2\.[^\n]*MANAGEMENT[^\n]*\n(.*?)\n\s*ITEM\s+3\.', re.IGNORECASE | re.DOTALL)
        item2_matches = item2_pattern.findall(clean_text)
        if item2_matches:
            extracted_text += "=== [ ITEM 2 (경영진의 진단 및 분석 - MD&A) ] ===\n"
            extracted_text += max(item2_matches, key=len).strip() + "\n\n"

    return extracted_text

# ==========================================
# 🇰🇷 한국 공시 추출용 내부 엔진 (함수)
# ==========================================
if 'api_key' not in st.session_state:
    if "dart_api_key" in st.secrets:
        st.session_state.api_key = st.secrets["dart_api_key"]
    else:
        st.session_state.api_key = None

@st.cache_data(ttl=600)
def fetch_kr_report_list(corp_query, start_date, end_date, api_key):
    try:
        dart = OpenDartReader(api_key)
        if corp_query.isdigit() and len(corp_query) == 6:
            corp_list = dart.corp_codes
            target_row = corp_list[corp_list['stock_code'] == corp_query]
            if target_row.empty: return None, corp_query
            corp_code = target_row.iloc[0]['corp_code']
            actual_corp_name = target_row.iloc[0]['corp_name']
        else:
            corp_code = dart.find_corp_code(corp_query)
            actual_corp_name = corp_query
            
        if not corp_code: return None, corp_query
    except:
        return None, corp_query

    url = "https://opendart.fss.or.kr/api/list.json"
    params = {'crtfc_key': api_key, 'corp_code': corp_code, 'bgn_de': start_date, 'end_de': end_date, 'pblntf_ty': 'A', 'page_count': 100}
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()
        if data.get('status') == '000': return pd.DataFrame(data['list']), actual_corp_name
        else: return pd.DataFrame(), actual_corp_name 
    except:
        return None, corp_query

def filter_kr_reports(df, selected_types):
    if df is None or len(df) == 0: return df
    df = df.copy().sort_values(by='rcept_dt', ascending=False).reset_index(drop=True)
    smart_types = []
    for idx, row in df.iterrows():
        nm = row['report_nm']
        month = int(row['rcept_dt'][4:6]) 
        r_type = "기타"
        if "사업보고서" in nm: r_type = "사업보고서"
        elif "반기보고서" in nm: r_type = "반기보고서"
        elif "분기보고서" in nm:
            if "1분기" in nm or 4 <= month <= 6: r_type = "1분기보고서"
            elif "3분기" in nm or 9 <= month <= 12: r_type = "3분기보고서"
            else: r_type = "분기보고서(기타)"
        smart_types.append(r_type)

    df['smart_type'] = smart_types
    filtered_df = df[df['smart_type'].isin(selected_types)].copy()
    if not filtered_df.empty:
        filtered_df['year_key'] = filtered_df['rcept_dt'].str[:4]
        return filtered_df.drop_duplicates(subset=['smart_type', 'year_key'], keep='first').drop(columns=['year_key'])
    return filtered_df

def process_kr_document(html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    for s in soup(["script", "style", "head", "svg", "img"]): s.decompose()
    for nav in soup.find_all(text=re.compile(r"본문\s*위치로\s*이동|목차|TOP")): nav.extract()
    for table in soup.find_all("table"):
        rows = []
        headers = [th.get_text(strip=True) for th in table.find_all("th")]
        if headers:
            rows.append("| " + " | ".join(headers) + " |")
            rows.append("| " + " | ".join(["---"] * len(headers)) + " |")
        for tr in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if cells: rows.append("| " + " | ".join(cells) + " |")
        if rows: table.replace_with("\n" + "\n".join(rows) + "\n")
            
    lines = soup.get_text(separator="\n").split('\n')
    blacklist = ["V. 회계감사인", "VI. 이사회", "X. 대주주", "XII. 상세표"]
    all_markers = ["I. 회사의 개요", "II. 사업의 내용", "III. 재무에 관한 사항", "IV. 이사의 진단", "V. 회계감사인", "VI. 이사회", "VII. 주주에 관한 사항", "VIII. 임원 및 직원", "IX. 계열회사", "X. 대주주", "XI. 그 밖에 투자자 보호", "XII. 상세표", "【", "첨부서류"]

    extracted_lines, skip_mode = [], False
    for line in lines:
        clean = line.strip()
        if any(clean.startswith(m) for m in all_markers):
            skip_mode = any(clean.startswith(b) for b in blacklist)
        if not skip_mode: extracted_lines.append(line)
            
    filtered_text = "\n".join(extracted_lines)
    filtered_text = re.sub(r' +', ' ', filtered_text)
    return re.sub(r'\n\s*\n+', '\n\n', filtered_text).strip()

# ==========================================
# 🚀 사이드바 메뉴 및 메인 화면 구성
# ==========================================
with st.sidebar:
    st.title("💡 투자 분석 메뉴")
    st.markdown("---")
    menu_choice = st.radio(
        "사용할 프로그램을 선택하세요:",
        ["🇰🇷 한국 공시 추출", "🇺🇸 미국 공시 추출"],
        index=0
    )
    st.markdown("---")
    st.info("선택과 집중을 위해 안 쓰시는 기술적 분석 탭은 깔끔하게 제거했습니다! 핵심 공시에만 집중해 보세요.")

# ------------------------------------------
# 화면 1: 한국 공시 추출 프로그램
# ------------------------------------------
if menu_choice == "🇰🇷 한국 공시 추출":
    st.title("⚡ 한국 DART 공시 원클릭 (AI 최적화)")
    
    if not st.session_state.api_key:
        st.error("DART API 키가 설정되지 않았습니다. secrets.toml 파일을 확인해주세요.")
        st.stop()
        
    with st.container(border=True):
        col_input, col_btn = st.columns([4, 1])
        with col_input:
            corp_name_input = st.text_input("회사명 또는 6자리 종목코드 입력", placeholder="예: 삼성전자 또는 005930", label_visibility="collapsed")
        with col_btn:
            btn_kr_start = st.button("검색", type="primary", use_container_width=True)

        with st.expander("📅 설정", expanded=True):
            col1, col2, col3 = st.columns([1, 1, 2])
            with col1: start_year = st.number_input("시작", 2000, 2030, 2024)
            with col2: end_year = st.number_input("종료", 2000, 2030, 2025)
            with col3: selected_types = st.multiselect("종류", ["1분기보고서", "반기보고서", "3분기보고서", "사업보고서"], default=["사업보고서"])

    if btn_kr_start and corp_name_input:
        start_date, end_date = f"{start_year}0101", f"{end_year}1231"
        with st.spinner(f"📡 '{corp_name_input}' 공시 목록을 가져오는 중..."):
            result = fetch_kr_report_list(corp_name_input.strip(), start_date, end_date, st.session_state.api_key)
            raw_df, actual_corp_name = result if result else (None, corp_name_input)

            if raw_df is not None and not raw_df.empty:
                df = filter_kr_reports(raw_df, selected_types)
                if not df.empty:
                    st.dataframe(df[['rcept_dt', 'report_nm', 'smart_type']], use_container_width=True, hide_index=True)
                    with st.status("🚀 텍스트 변환 및 ZIP 생성 중...", expanded=True) as status:
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                            for i, (idx, row) in enumerate(df.iterrows()):
                                rpt_name, rcept_no = row['report_nm'], row['rcept_no']
                                fname = re.sub(r'[\\/*?:"<>|]', "", f"{actual_corp_name}_{rpt_name}.txt")
                                status.write(f"📥 ({i+1}/{len(df)}) 저장: {fname}")
                                try:
                                    d_url = f"https://opendart.fss.or.kr/api/document.xml?crtfc_key={st.session_state.api_key}&rcept_no={rcept_no}"
                                    res = requests.get(d_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
                                    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
                                        t_file = max(z.infolist(), key=lambda f: f.file_size).filename
                                        content = z.read(t_file).decode('utf-8', 'ignore')
                                        final_txt = process_kr_document(content)
                                        header = f"### {actual_corp_name} {rpt_name} ###\n접수일: {row['rcept_dt']}\n분류: {row['smart_type']}\n\n"
                                        zip_file.writestr(fname, header + final_txt)
                                except:
                                    status.write(f"⚠️ 실패: {fname}")
                        status.update(label="🎉 압축 완료!", state="complete", expanded=False)
                    st.download_button("💾 DART 공시 ZIP 저장", data=zip_buffer.getvalue(), file_name=f"{actual_corp_name}_공시모음.zip", mime="application/zip", type="primary", use_container_width=True)
                else: st.warning("조건에 맞는 보고서가 없습니다.")
            else: st.error("❌ 검색된 공시가 없습니다.")

# ------------------------------------------
# 화면 2: 미국 공시 추출 프로그램
# ------------------------------------------
elif menu_choice == "🇺🇸 미국 공시 추출":
    st.title("🦅 미국 SEC 10-K / 10-Q 액기스 추출")
    
    with st.container(border=True):
        col_input_us, col_btn_us = st.columns([4, 1])
        with col_input_us:
            ticker_input = st.text_input("미국 주식 티커 (예: NVDA, AAPL)", placeholder="티커 입력", label_visibility="collapsed").strip().upper()
        with col_btn_us:
            btn_us_start = st.button("추출 시작", type="primary", use_container_width=True)

        with st.expander("📅 연도 및 종류 설정", expanded=True):
            col1, col2 = st.columns(2)
            current_year = datetime.now().year
            years = list(range(current_year, 2010, -1))
            with col1: start_year_us = st.selectbox("시작 연도", years, index=3)
            with col2: end_year_us = st.selectbox("종료 연도", years, index=0)
            
            st.markdown("📑 **보고서 종류**")
            c1, c2, c3, c4 = st.columns(4)
            with c1: chk_1q = st.checkbox("1분기(10-Q)", value=True)
            with c2: chk_2q = st.checkbox("2분기(10-Q)", value=True)
            with c3: chk_3q = st.checkbox("3분기(10-Q)", value=True)
            with c4: chk_10k = st.checkbox("연간(10-K)", value=True)

    if btn_us_start and ticker_input:
        selected_forms_us = []
        if chk_1q: selected_forms_us.append("1분기")
        if chk_2q: selected_forms_us.append("2분기")
        if chk_3q: selected_forms_us.append("3분기")
        if chk_10k: selected_forms_us.append("10-K")
        
        if not selected_forms_us:
            st.warning("보고서 종류를 최소 1개 이상 선택해주세요.")
        elif start_year_us > end_year_us:
            st.warning("시작 연도가 종료 연도보다 클 수 없습니다.")
        else:
            with st.status("🔍 SEC 데이터베이스 조회 중...", expanded=True) as status:
                st.write("1단계: CIK 번호 확인...")
                cik = get_cik(ticker_input)
                
                if not cik:
                    status.update(label="❌ 티커를 찾을 수 없습니다.", state="error")
                    st.stop()
                    
                st.write("2단계: 문서 목록 필터링 중...")
                target_filings = fetch_us_filings(cik, start_year_us, end_year_us, selected_forms_us)
                
                if not target_filings:
                    status.update(label="❌ 조건에 맞는 보고서가 없습니다.", state="error")
                    st.stop()
                    
                st.write(f"3단계: 총 {len(target_filings)}건 텍스트 정제 및 압축 중...")
                zip_buffer_us = io.BytesIO()
                success_count = 0
                
                with zipfile.ZipFile(zip_buffer_us, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    for i, filing in enumerate(target_filings):
                        year, form, q_label = filing['year'], filing['form'], filing['q_label']
                        file_name = f"{ticker_input}_{year}_{form}.txt" if form == '10-K' else f"{ticker_input}_{year} {q_label}_{form}.txt"
                        try:
                            extracted_text = process_us_document(ticker_input, filing['url'], form)
                            zip_file.writestr(file_name, extracted_text)
                            success_count += 1
                        except:
                            st.write(f"⚠️ {file_name} 추출 실패")
                            
                status.update(label=f"✅ 작업 완료! (총 {success_count}건 성공)", state="complete", expanded=False)
                
            if success_count > 0:
                zip_filename_us = f"{ticker_input}_{start_year_us}-{end_year_us}_SEC공시.zip"
                st.download_button("💾 SEC 공시 ZIP 저장", data=zip_buffer_us.getvalue(), file_name=zip_filename_us, mime="application/zip", type="primary", use_container_width=True)
