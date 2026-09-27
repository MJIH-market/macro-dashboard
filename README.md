# 매크로 지표 대시보드 설정 가이드

매일 08:00(KST)에 GitHub Actions가 11개 지표의 최근 5년 데이터를 수집합니다. 수집한 데이터로 대시보드 페이지(1년/3년/5년 전환)를 갱신합니다.

## 지표와 소스

| 지표 | 1순위 | 예비 |
|---|---|---|
| S&P 500 | FRED SP500 (공식) | Yahoo ^GSPC |
| 나스닥100 | FRED NASDAQ100 (공식) | Yahoo ^NDX |
| 원/달러 | 한국은행 ECOS 매매기준율 (공식) | Yahoo KRW=X → FRED DEXKOUS |
| 엔/달러 | Yahoo JPY=X | FRED DEXJPUS (주 1회 갱신) |
| 달러인덱스(ICE DXY) | Yahoo DX-Y.NYB (비공식) | 없음 |
| 미국채 2년 / 10년 | FRED DGS2 / DGS10 (공식) | 없음 |
| 일본국채 30년 | 일본 재무성 JGB 금리 CSV (공식) | 없음 |
| WTI 선물 / 금 선물 | Yahoo CL=F / GC=F (비공식) | 없음 |
| VIX | FRED VIXCLS (공식) | Yahoo ^VIX |

- 모든 소스 수집에 실패하면 직전 저장 데이터를 표시하고 '이전 데이터'로 표시합니다.
- 대체 소스를 쓴 경우 '예비 소스'로 표시합니다.

---

## 1단계. API 키 발급

| 키 | 필수 여부 | 발급 방법 |
|---|---|---|
| FRED_API_KEY | 필수 | https://fredaccount.stlouisfed.org 에서 회원가입 후 My Account → API Keys → Request API Key (즉시 발급) |
| ECOS_API_KEY | 선택 | https://ecos.bok.or.kr/api 에서 회원가입 후 인증키 신청 (보통 당일~수일 소요) |

ECOS 키가 없으면 원/달러는 Yahoo KRW=X로 자동 대체됩니다.

## 2단계. GitHub 저장소 생성 및 파일 업로드

1. https://github.com 에 로그인한 뒤, 우측 상단 + → New repository를 선택합니다.
2. 이름은 예를 들어 `macro-dashboard`로 하고, **Public**을 선택한 후 Create repository를 누릅니다.
   - 무료 계정에서 GitHub Pages를 쓰려면 Public이어야 합니다. 공개되는 것은 시장 데이터뿐입니다.
3. 저장소 화면에서 uploading an existing file을 누르고, 압축을 푼 폴더 안의 **모든 파일과 폴더**를 끌어다 놓은 뒤 Commit changes를 누릅니다.
   - `.github` 폴더는 숨김 폴더라 탐색기/Finder에서 보이지 않을 수 있습니다. 업로드 후 저장소에 `.github/workflows/update.yml`이 있는지 반드시 확인하세요.
   - 없다면 Add file → Create new file을 누르고, 파일명 칸에 `.github/workflows/update.yml`을 입력한 뒤 내용을 붙여넣어 커밋합니다.

## 3단계. API 키 등록 (Secrets)

저장소 Settings → Secrets and variables → Actions → New repository secret으로 이동합니다.

- Name `FRED_API_KEY`, Secret에는 발급받은 키를 입력합니다.
- (선택) Name `ECOS_API_KEY`도 같은 방식으로 등록합니다.

## 4단계. 쓰기 권한 확인

Settings → Actions → General → Workflow permissions에서 **Read and write permissions**를 선택하고 Save를 누릅니다.

## 5단계. 첫 실행

1. Actions 탭으로 이동합니다. 워크플로 활성화 안내가 나오면 승인합니다.
2. 왼쪽에서 Update macro dashboard → Run workflow → Run workflow를 누릅니다.
3. 1~3분 후 초록 체크가 뜨는지 확인합니다. 실패 시 로그의 `FAIL` 줄을 확인하세요.

## 6단계. 대시보드 공개 (GitHub Pages)

1. Settings → Pages로 이동합니다.
2. Source는 Deploy from a branch, Branch는 `main`, 폴더는 `/docs`로 지정하고 Save를 누릅니다.
3. 1~2분 후 `https://<GitHub아이디>.github.io/macro-dashboard/` 주소로 접속하면 됩니다. 이 주소를 북마크해 두세요.

이후에는 매일 08:00 KST 전후로 자동 갱신됩니다.

---

## 운영 참고

- **데이터 기준일:** FRED 금리, VIX 등은 미국 영업일 기준으로 통상 1영업일 늦게 게시됩니다. 08:00 KST 실행 시 직전 또는 전전 영업일 값이 최신일 수 있습니다.
- **Yahoo 소스:** 비공식 소스라 간헐적으로 차단되거나 형식이 바뀔 수 있습니다. 실패 시 직전 데이터가 유지되며, 오류가 반복되면 `pip install -U yfinance`로 버전을 확인하세요.
- **예약 실행 중단:** 공개 저장소는 60일간 활동이 없으면 예약 실행이 중지될 수 있습니다. GitHub가 사전에 메일을 보내며, Actions 탭에서 다시 활성화하면 됩니다.
- **원자료:** 수집된 원자료는 `data/*.csv`에 누적되어 엑셀로 바로 열 수 있습니다.
- **로컬 실행:**
  ```bash
  pip install -r requirements.txt
  set FRED_API_KEY=발급키          # macOS/Linux는 export FRED_API_KEY=발급키
  python macro_dashboard.py         # docs/index.html 생성
  ```
- **지표 추가/변경:** `macro_dashboard.py` 상단의 `INDICATORS` 목록에 한 줄을 추가하면 됩니다. 예를 들어 FRED 시리즈라면 `("fred", "시리즈ID")`를 넣습니다.
