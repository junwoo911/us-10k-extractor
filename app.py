import streamlit as st
import requests
from bs4 import BeautifulSoup
import re
import io
import zipfile
from datetime import datetime

# --- 페이지 기본 설정 ---
st.set_page_config(page_title="미국 공시 액기스 추출기", page_icon="🇺🇸", layout="centered")

HEADERS = {'User-Agent': 'MyCompanyName (myemail@gmail.com)'}

def get_cik(ticker):
    url = "https://www.sec.gov/files/company_tickers.json"
    try:
        res = requests.get(url, headers=HEADERS)
        data = res.json()
        ticker = ticker.upper()
        for key, val in data.items():
            if val['ticker'] == ticker:
                return str(val['cik_str']).zfill(10)
    except:
        pass
    return None

def fetch_filings(cik, start_year, end_year, selected_forms):
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    res = requests.get(url, headers=HEADERS)
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

def process_document_to_text(ticker, url, form_type):
    res = requests.get(url, headers=HEADERS)
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

# --- UI 세팅 ---
st.title("🦅 미국 공시 액기스 추출기")
st.markdown("미국 10-K 및 10-Q 보고서의 핵심(사업내용, 위험요소, MD&A)만 정밀하게 추출합니다.")

ticker_input = st.text_input("기업 티커 (예: NVDA, AAPL)", placeholder="티커를 입력하세요").strip().upper()

col1, col2 = st.columns(2)
current_year = datetime.now().year
years = list(range(current_year, 2010, -1))
with col1:
    start_year = st.selectbox("시작 연도", years, index=3)
with col2:
    end_year = st.selectbox("종료 연도", years, index=0)

st.markdown("#### 📑 보고서 종류 선택")
col3, col4, col5, col6 = st.columns(4)
with col3: chk_1q = st.checkbox("1분기(10-Q)", value=True)
with col4: chk_2q = st.checkbox("2분기(10-Q)", value=True)
with col5: chk_3q = st.checkbox("3분기(10-Q)", value=True)
with col6: chk_10k = st.checkbox("연간(10-K)", value=True)

if st.button("🚀 데이터 추출 및 압축 시작", use_container_width=True):
    selected_forms = []
    if chk_1q: selected_forms.append("1분기")
    if chk_2q: selected_forms.append("2분기")
    if chk_3q: selected_forms.append("3분기")
    if chk_10k: selected_forms.append("10-K")
    
    if not ticker_input:
        st.warning("티커를 입력해주세요.")
    elif not selected_forms:
        st.warning("보고서 종류를 최소 1개 이상 선택해주세요.")
    elif start_year > end_year:
        st.warning("시작 연도가 종료 연도보다 클 수 없습니다.")
    else:
        with st.status("🔍 SEC 데이터베이스 접속 중...", expanded=True) as status:
            st.write("1단계: SEC 고유번호(CIK) 조회...")
            cik = get_cik(ticker_input)
            
            if not cik:
                status.update(label="❌ 티커를 찾을 수 없습니다.", state="error")
                st.stop()
                
            st.write("2단계: 문서 목록 필터링 중...")
            target_filings = fetch_filings(cik, start_year, end_year, selected_forms)
            
            if not target_filings:
                status.update(label="❌ 조건에 맞는 보고서가 없습니다.", state="error")
                st.stop()
                
            st.write(f"3단계: 총 {len(target_filings)}건 다운로드 및 텍스트 정제 중...")
            
            # 메모리 상에서 ZIP 파일 생성
            zip_buffer = io.BytesIO()
            success_count = 0
            
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for i, filing in enumerate(target_filings):
                    year = filing['year']
                    form = filing['form']
                    q_label = filing['q_label']
                    
                    if form == '10-K':
                        file_name = f"{ticker_input}_{year}_{form}.txt"
                    else:
                        file_name = f"{ticker_input}_{year} {q_label}_{form}.txt"
                        
                    try:
                        extracted_text = process_document_to_text(ticker_input, filing['url'], form)
                        zip_file.writestr(file_name, extracted_text)
                        success_count += 1
                    except Exception as e:
                        st.write(f"⚠️ {file_name} 추출 실패")
                        
            status.update(label=f"✅ 작업 완료! (총 {success_count}건 성공)", state="complete", expanded=False)
            
        if success_count > 0:
            zip_filename = f"{ticker_input}_{start_year}-{end_year}_공시모음.zip"
            st.success("🎉 압축 파일이 준비되었습니다! 아래 버튼을 눌러 다운로드하세요.")
            st.download_button(
                label=f"💾 {zip_filename} 다운로드",
                data=zip_buffer.getvalue(),
                file_name=zip_filename,
                mime="application/zip",
                type="primary",
                use_container_width=True
            )