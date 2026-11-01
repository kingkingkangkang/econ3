# 오늘의 경제 3

평일(월~금) 아침 8시에 주요 경제뉴스 3개를 골라 요약하고, 모바일 웹페이지로 만들어 카카오톡 '나에게 보내기'로 보내줘요.

```
07:40  GitHub Actions 자동 시작
  ├ 1. 5개 매체에서 후보 기사 수집 (Claude Haiku + 웹검색)
  ├ 2. 같은 이슈 묶기, 100점 점수 매기기 (Claude Sonnet)
  ├ 3. 요약에 쓸 자료 찾기: 무료 본문 → 원래 발표 자료 → 3개 매체 교차 확인(특이사항) → 제외
  ├ 4. 한국어 요약 쓰기 (Claude Sonnet)
  ├ 5. 웹페이지 만들기 → GitHub Pages에 올리기
08:00  카톡 발송: 제목 3개 + [자세히 보기] 버튼
```

처음 한 번만 아래 설정을 해주면 그다음부터는 자동이에요. 30~40분쯤 걸려요.

---

## 0. 준비물

- GitHub 계정 (없으면 github.com에서 무료 가입)
- 카카오 계정
- Claude API 키 (4번에서 설명)

아래 설명의 `아이디`는 GitHub 아이디, `econ3`는 저장소 이름이에요. 저장소 이름을 다르게 지었다면 그 이름으로 바꿔 읽으세요.

---

## 1. GitHub 저장소 만들기

1. github.com 오른쪽 위 **+** → **New repository**
2. Repository name: `econ3`, **Public** 선택 → **Create repository**
3. 만들어진 화면에서 **uploading an existing file** 클릭
4. 받은 zip을 풀고, **폴더 안의 내용물 전체**를 끌어다 놓기 → **Commit changes**

**업로드 후 꼭 확인**: 저장소에 `.github` 폴더가 보여야 해요. Mac에서는 점(.)으로 시작하는 폴더가 숨겨져 있어서 빠질 수 있어요.
- 안 보이면: **Add file → Create new file** → 파일 이름 칸에 `.github/workflows/daily.yml` 입력 → `setup/workflows/daily.yml` 내용을 그대로 붙여넣기 → Commit
- `pages.yml`, `kakao-setup.yml`도 같은 방법으로 만들어요.

---

## 2. GitHub 설정

1. 저장소 **Settings → Pages** → Build and deployment의 Source를 **GitHub Actions**로 선택
2. 저장소 **Settings → Actions → General** → 맨 아래 Workflow permissions에서 **Read and write permissions** 선택 → Save
3. 저장소 **Actions** 탭 → 왼쪽 **웹페이지 배포** → **Run workflow** → 1분쯤 뒤
   `https://아이디.github.io/econ3/` 가 열리면 성공이에요. (Actions 탭에서 워크플로 사용 확인 버튼이 나오면 먼저 눌러주세요.)
   - 파일을 올린 직후 '웹페이지 배포'가 빨간 X로 실패해 있을 수 있어요. Pages 설정 전에 실행돼서 그런 거라 괜찮아요.

---

## 3. 카카오 앱 만들기

[developers.kakao.com](https://developers.kakao.com) 로그인 → **내 애플리케이션** → **애플리케이션 추가하기** (앱 이름 예: 오늘의 경제 3)

만든 앱에 들어가서:

| 할 일 | 메뉴 위치 |
|---|---|
| 카카오 로그인 켜기 | [카카오 로그인] → [사용 설정] → 상태 **ON** |
| 메시지 권한 | [카카오 로그인] → [동의항목] → 접근권한의 **카카오톡 메시지 전송** → 설정 → **선택 동의** → 저장 |
| REST API 키 복사 | [앱] → [플랫폼 키] → [REST API 키] |
| 리다이렉트 URI 등록 | 같은 화면의 리다이렉트 URI에 `https://아이디.github.io/econ3/` 등록 (끝의 `/`까지 정확히) |
| 클라이언트 시크릿 복사 | 같은 화면의 [클라이언트 시크릿] 코드 (새 앱은 기본으로 켜져 있어요) |
| 웹 도메인 등록 | [앱] → [제품 링크 관리] → [웹 도메인]에 `https://아이디.github.io` 등록 |

카카오 콘솔 화면 구성은 가끔 바뀌어요. 메뉴 이름이 조금 다르면 비슷한 이름을 찾으면 돼요.

---

## 4. Claude API 키 만들기

뉴스 수집·요약에 Claude API를 써요. 예상 비용은 **한 달 약 $5~10**이고, 실제 사용량은 매일 Actions 실행 결과 화면에 표로 나와요.

**방법 A: 팀 플랜 크레딧 쓰기 (추천)**
Claude Team 플랜 Standard 좌석에는 매달 1인당 $20의 API 크레딧이 포함돼요.
1. 팀 **Owner**가 Claude 조직 설정에서 콘솔 조직을 연결해요. (가입 후 7일이 지나야 받을 수 있어요.)
2. 그 콘솔 조직에 초대받은 뒤, Claude 콘솔(platform.claude.com) → **API Keys** → **Create Key**
- 크레딧은 다음 달로 넘어가지 않아요.

**방법 B: 개인 결제**
Claude 콘솔(platform.claude.com) 가입 → 결제 수단 등록·크레딧 충전 → **API Keys** → **Create Key**

만든 키(`sk-ant-...`)는 한 번만 보여요. 바로 6번에서 등록하세요.

---

## 5. GitHub 토큰 만들기 (GH_PAT)

카카오 로그인 토큰은 약 2개월마다 새로 발급돼요. 새 토큰을 자동으로 저장하려면 이 토큰이 필요해요.

1. GitHub 오른쪽 위 프로필 → **Settings** → 맨 아래 **Developer settings**
2. **Personal access tokens → Fine-grained tokens → Generate new token**
3. Expiration: 원하는 기간 (최대 1년. 만료되면 새로 만들어 다시 등록)
4. Repository access: **Only select repositories** → `econ3`
5. Permissions → Repository permissions → **Secrets: Read and write**
6. **Generate token** → 나온 값 복사

---

## 6. 비밀값(Secrets) 등록

저장소 **Settings → Secrets and variables → Actions → New repository secret**으로 5개를 등록해요.

| 이름 | 값 |
|---|---|
| `ANTHROPIC_API_KEY` | 4번의 Claude API 키 |
| `KAKAO_REST_API_KEY` | 3번의 REST API 키 |
| `KAKAO_CLIENT_SECRET` | 3번의 클라이언트 시크릿 코드 |
| `KAKAO_REDIRECT_URI` | `https://아이디.github.io/econ3/` (3번에 등록한 값과 똑같이) |
| `GH_PAT` | 5번의 GitHub 토큰 |

---

## 7. 카카오 연결 (최초 1회)

1. 아래 주소의 【】 부분을 바꿔서 브라우저 주소창에 넣어요.
   ```
   https://kauth.kakao.com/oauth/authorize?response_type=code&client_id=【REST API 키】&redirect_uri=【리다이렉트 URI】&scope=talk_message
   ```
2. 카카오 로그인 → 동의하면 내 웹페이지로 돌아오고, 화면 위에 **카카오 인증 코드** 상자가 나와요 → **복사**
3. 저장소 **Actions** → **카카오 연결 (최초 1회)** → **Run workflow** → 코드 붙여넣기 → 실행
   - 코드는 몇 분 안에 써야 해요. 실패하면 1번부터 다시 하면 돼요.
4. 카톡 나와의 채팅에 **"카카오 연결 완료!"** 가 오면 성공이에요.

---

## 8. 첫 실행 테스트

저장소 **Actions** → **오늘의 경제 3** → **Run workflow** (카톡 보내기 체크) → 실행

5~10분 뒤 카톡이 와요. 실행 기록을 누르면 **선정 결과, 카톡 미리보기, 토큰 사용량·비용**이 보여요.

여기까지 되면 끝이에요. 이제 **평일 아침 8시**마다 자동으로 와요.

---

## 운영 안내

**알아두면 좋은 점**
- GitHub 자동 실행은 붐비는 시간에 5~20분 늦게 시작할 수 있어요. 일찍 끝나면 8시까지 기다렸다가 보내요.
- 만들기에 실패하면 "오늘 뉴스를 만들지 못했어요" 카톡이 와요. Actions 탭에서 빨간 X 기록을 열어보면 원인이 나와요.
- 저장소와 웹페이지는 공개라서 주소를 아는 사람은 볼 수 있어요. 검색엔진 노출은 막아뒀어요.
- 요약은 직접 풀어 쓴 문장과 원문 링크로만 구성해요. 기사 원문을 옮겨 싣지 않아요.

**바꾸고 싶을 때**

| 바꿀 것 | 파일 |
|---|---|
| 발송 시각 | `news/config.py`의 `SEND_HOUR` + `.github/workflows/daily.yml`의 `cron` (UTC 기준, 시작은 20분 전) |
| 매체 목록, 모델, 점수 기준값 | `news/config.py` (추가한 매체가 막혀 있으면 실행 중 자동으로 빠져요) |
| 기사 선정·요약 규칙 문장 | `news/prompts.py` |
| 웹페이지 디자인 | `news/templates/` |

**문제 해결**

| 증상 | 확인할 것 |
|---|---|
| `KOE006` | `KAKAO_REDIRECT_URI`가 카카오 앱에 등록한 값과 글자 하나까지 같은지 |
| `KOE010` | `KAKAO_CLIENT_SECRET` 값 |
| `KOE320` | 인증 코드 만료 → 7번 1단계부터 다시 |
| `KOE322` / 리프레시 토큰 만료 | 7번(카카오 연결)을 다시 실행. GH_PAT이 만료되지 않았는지도 확인 |
| `-402` | 3번의 '카카오톡 메시지 전송' 동의항목 설정 후 7번 다시 |
| 카톡 버튼을 눌러도 페이지가 안 열림 | 3번의 웹 도메인 등록 (`https://아이디.github.io`) |
| `ANTHROPIC_API_KEY` 오류 / 401 | API 키 값, 콘솔 크레딧 잔액 |

## 기사 선정 기준 (요약)

- **매체 5곳**: 유료 Bloomberg·Nikkei Asia·CNN Business / 무료 CNBC·Yahoo Finance (Yahoo에는 Reuters·AP 기사도 실려요)
  - WSJ·FT·The Economist·Barron's·Reuters·AP·The Guardian·BBC는 Anthropic의 자동 접근을 막아두어 쓸 수 없어요. 막힌 매체는 실행 중에 자동으로 빠져요.
- **수집 범위**: 화~금은 전날 08:00부터 24시간, 월요일은 금요일 08:00부터 (한국시간)
- **점수(100)**: 파급력 30, 한국 연관성 25, 새로움 20, 후속성 15, 설명 가능성 10
- **동점**: 실제 발표·결정 > 발언·전망 > 해설·분석
- **분야 균형**: 거시·정책 / 시장 / 기업·산업에서 1개씩. 50점 미만 분야는 다른 분야 차점으로 채우되 한 분야 최대 2개. CPI·고용보고서·FOMC 발표일엔 그 기사가 거시 1순위
- **요약 자료**: ① Yahoo Finance 무료 본문 → ② 원래 발표 자료(BLS·BEA·USTR·연준·Business Wire) → ③ 3개 이상 매체의 제목과 공개된 부분이 모두 일치하면 **특이사항**으로 표시하고 이유를 적어요 → ④ 그것도 안 되면 제외
- **링크**: 실제로 읽은 무료 원문. ③은 사람이 무료로 볼 수 있는 매체 우선, 없으면 "유료" 표시
