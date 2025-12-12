# Naver Maps Directions for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

네이버 지도 API를 사용하여 경로의 예상 소요 시간을 Home Assistant 센서로 제공하는 커스텀 통합입니다.

## 주요 기능

- 🚗 **실시간 교통 정보 반영** - 네이버 지도의 실시간 교통 상황을 반영한 ETA 제공
- 📍 **다양한 위치 입력 방식**
  - Home Assistant 엔티티 (`person.xxx`, `device_tracker.xxx`, `zone.xxx`)
  - 주소 텍스트 (예: `서울시 강남구 역삼동 123`)
  - 직접 좌표 입력 (예: `127.12345, 37.12345`)
- 🛣️ **다중 경유지 지원** - 최대 5개까지 경유지 설정 가능
- 📊 **히스토리 그래프 지원** - 시간대별 소요 시간 변화를 그래프로 확인
- ⚡ **스마트 캐싱** - 텍스트 주소는 한 번만 Geocoding하여 API 호출 최소화

## 필요한 API

### Naver Cloud Platform 설정

1. [Naver Cloud Platform](https://www.ncloud.com/) 가입
2. **Console** → **Services** → **AI·Application Service** → **Maps** 이동
3. **Application 등록** 클릭하여 새 애플리케이션 생성
4. 다음 API들을 활성화:

| API | 용도 | 필수 여부 |
|-----|------|----------|
| **Directions 5** | 경로 탐색 및 소요 시간 조회 | ✅ 필수 |
| **Geocoding** | 주소 → 좌표 변환 | ✅ 필수 (주소 입력 시) |

> **참고**: 좌표를 직접 입력하거나 Home Assistant 엔티티만 사용하는 경우 Geocoding API는 불필요합니다.

5. 생성된 **API Key ID**와 **API Key**를 복사

### API 요금

- Naver Cloud Platform Maps API는 **월 일정량 무료** 제공
- 자세한 요금은 [Naver Cloud Platform 요금](https://www.ncloud.com/charge/calc/ko) 참조

## 설치

### HACS (권장)

1. HACS → **Integrations** → 우측 상단 메뉴 → **Custom repositories**
2. URL: `https://github.com/SJang1/ha-navermaps` 입력
3. Category: **Integration** 선택
4. **Naver Maps Directions** 검색 후 설치
5. Home Assistant 재시작

### 수동 설치

1. `custom_components/ha-navermaps` 폴더를 Home Assistant의 `custom_components` 디렉토리에 복사
2. Home Assistant 재시작

## 설정

### 초기 설정

1. **설정** → **기기 및 서비스** → **통합 추가**
2. **Naver Maps** 검색
3. API Key ID와 API Key 입력

### 경로 추가

1. Naver Maps 통합의 **설정** 클릭
2. **➕ 새 경로 추가** 선택
3. 출발지/도착지 입력:
   - **엔티티 선택**: `person.xxx`, `device_tracker.xxx`, `zone.home` 등
   - **주소 입력**: `서울시 강남구 역삼동 123`
   - **좌표 입력**: `127.12345, 37.12345` (경도, 위도 순서)
4. (선택) **📍 경유지 추가** - 최대 5개까지 추가 가능
5. 경로 옵션 선택:
   - **실시간 최적**: 교통 상황을 고려한 최적 경로
   - **실시간 빠른 길**: 가장 빠른 경로
   - **실시간 편한 길**: 회전이 적은 편한 경로
   - **무료 우선**: 톨게이트 회피
   - **자동차 전용 도로 회피**: 자동차 전용 도로 제외
6. **✅ 경로 저장**

## 센서 속성

| 속성 | 설명 | 단위 |
|------|------|------|
| `state` | 예상 소요 시간 | 분 |
| `distance` | 총 거리 | km |
| `duration_seconds` | 예상 소요 시간 | 초 |
| `toll_fare` | 통행료 | 원 |
| `taxi_fare` | 예상 택시 요금 | 원 |
| `fuel_price` | 예상 유류비 | 원 |
| `waypoints` | 경유지 목록 | - |
| `waypoint_count` | 경유지 개수 | - |
| `priority` | 경로 옵션 | - |
| `last_update` | 마지막 업데이트 시간 | - |

## 사용 예시

### Lovelace 카드

```yaml
type: entities
entities:
  - entity: sensor.home_to_office
    name: 집 → 회사
```

### 히스토리 그래프

```yaml
type: history-graph
entities:
  - entity: sensor.home_to_office
hours_to_show: 24
title: 출퇴근 소요 시간
```

### 자동화 예시

```yaml
automation:
  - alias: "출근 시간 알림"
    trigger:
      - platform: time
        at: "07:30:00"
    condition:
      - condition: numeric_state
        entity_id: sensor.home_to_office
        above: 60
    action:
      - service: notify.mobile_app
        data:
          title: "교통 혼잡"
          message: "출근 예상 시간: {{ states('sensor.home_to_office') }}분"
```

### 템플릿 센서

```yaml
template:
  - sensor:
      - name: "출근 예상 도착 시간"
        state: >
          {{ (now() + timedelta(minutes=states('sensor.home_to_office')|int)).strftime('%H:%M') }}
```

## 문제 해결

### API 오류

- **401 Unauthorized**: API Key가 잘못되었습니다. Key ID와 Key를 확인하세요.
- **429 Too Many Requests**: API 호출 한도 초과. 업데이트 주기를 늘리세요.
- **경로를 찾을 수 없음**: 출발지/도착지가 도로와 너무 멀거나 잘못된 주소입니다.

### 로그 확인

```yaml
logger:
  default: warning
  logs:
    custom_components.ha-navermaps: debug
```

## 라이선스

MIT License

## 기여

이슈 및 PR 환영합니다!

- GitHub: https://github.com/SJang1/ha-navermaps
